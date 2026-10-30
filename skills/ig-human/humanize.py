#!/usr/bin/env python3
"""
humanize.py - strip the machine fingerprint out of a draft.

Three passes, in this order:

  1. INVISIBLE   delete or normalise the characters a human keyboard never
                 produces: zero-width joiners, word joiners, soft hyphens,
                 BOMs, Unicode tag characters, non-breaking and narrow spaces.
                 These survive copy-paste and are the most mechanical tell in
                 any generated text.
  2. TYPOGRAPHIC em dash -> comma, en dash -> hyphen, curly quotes -> straight,
                 ellipsis -> three dots, bullet -> hyphen, ё -> е.
  3. LEXICAL     replace the slop lexicon in slop.json with plain words,
                 preserving capitalisation and leaving URLs untouched.

The text language is detected (en, ru, kk) and only the lexicon entries for
that language run: English entries everywhere, Russian ones on Russian and
Kazakh text (Kazakh captions borrow Russian stock phrases), Kazakh ones on
Kazakh text only. Entries whose `replace` is null are inflected forms a regex
cannot rewrite grammatically: they are counted and FLAGGED, not replaced.

In Russian and Kazakh text "X — это Y" loses the dash ("X это Y"), every
other dash becomes a comma, and the report quotes each place so the ones that
were grammatical ("Алматы — ең үлкен қала") get rephrased by hand.

Structural tells (rule-of-three, "not just X, it's Y", hashtag walls) are
REPORTED, never auto-rewritten - rewriting a sentence's shape needs judgement,
so that is the model's job, not a regex's.

Usage
  python3 humanize.py draft.txt
  python3 humanize.py draft.txt --report
  pbpaste | python3 humanize.py - --report
  python3 humanize.py draft.txt --json
  python3 humanize.py draft.txt -o clean.txt
  python3 humanize.py draft.txt --lang kk     # skip detection
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")

# Letters Kazakh has and Russian does not, and short words only Kazakh uses.
# A Russian caption that names "Қанат" once is still Russian: the Russian
# function words outvote one letter.
KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
KK_WORDS = {"бұл", "және", "үшін", "емес", "жоқ", "ешкім", "керек", "болады", "деп",
            "мен", "сен", "сіз", "біз", "олар", "қалай", "неге", "қашан", "қандай",
            "бар", "бір", "ең", "тек", "бірақ", "енді", "осы", "сол", "мына", "кім"}
RU_WORDS = {"и", "в", "на", "что", "это", "как", "с", "по", "я", "ты", "вы", "мы",
            "он", "она", "они", "у", "к", "за", "из", "от", "для", "так", "все",
            "но", "а", "или", "если", "то", "бы", "же", "ли", "только", "уже",
            "когда", "где"}


def detect_lang(text):
    """'en', 'ru' or 'kk'."""
    text = re.sub(r"https?://\S+|www\.\S+|[@#]\w+", " ", text)
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    if not cyr or cyr < lat:
        return "en"
    toks = re.findall(r"[^\W\d_]+", text.lower())
    kk = sum(1 for c in text if c in KK_LETTERS) + 2 * sum(1 for t in toks if t in KK_WORDS)
    ru = 2 * sum(1 for t in toks if t in RU_WORDS)
    return "kk" if kk > ru else "ru"


def word_entry_applies(entry, lang):
    """Lexicon words and phrases: en everywhere, ru on ru and kk, kk on kk."""
    el = entry.get("lang", "en")
    return el == "en" or el == lang or (el == "ru" and lang == "kk")


def structure_applies(entry, lang):
    """Structural tells: en everywhere (emoji, hashtags), the rest by language."""
    el = entry.get("lang", "en")
    return el == "en" or el == lang


def entry_pattern(entry):
    """An entry's own regex if it has one, else its literal phrase."""
    if entry.get("pattern"):
        return re.compile(entry["pattern"], re.IGNORECASE)
    return re.compile(r"\b" + re.escape(entry["find"]).replace(r"\ ", r"\s+") + r"\b",
                      re.IGNORECASE)


def load_lexicon(path=LEX):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cp(spec):
    """'U+200B' -> '\\u200b';  'U+E0000-U+E007F' -> (start, end)."""
    if "-" in spec:
        a, b = spec.split("-")
        return (int(a[2:], 16), int(b[2:], 16))
    return int(spec[2:], 16)


def protect_urls(text):
    """Swap URLs for placeholders so no pass rewrites inside a link."""
    found = []

    def stash(m):
        found.append(m.group(0))
        return f"\x00URL{len(found) - 1}\x00"

    return URL_RE.sub(stash, text), found


def restore_urls(text, found):
    for i, url in enumerate(found):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def pass_invisible(text, lex):
    """Delete or space-normalise invisible characters. Returns (text, hits)."""
    hits = []
    for entry in lex["invisible"]:
        cp = _cp(entry["cp"])
        if isinstance(cp, tuple):
            pattern = "[" + re.escape(chr(cp[0])) + "-" + re.escape(chr(cp[1])) + "]"
        else:
            pattern = re.escape(chr(cp))
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"name": entry["cp"] + " " + entry["name"], "count": n,
                         "action": entry["action"]})
            text = re.sub(pattern, "" if entry["action"] == "delete" else " ", text)
    # Any remaining Cf (format) character is invisible by definition.
    stray = [c for c in text if unicodedata.category(c) == "Cf"]
    if stray:
        hits.append({"name": "other invisible format chars", "count": len(stray),
                     "action": "delete"})
        text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return text, hits


def _whole_words(text, m):
    """A match trimmed so it neither starts nor ends mid-word."""
    s = m.group(0)
    if m.start() > 0 and not text[m.start() - 1].isspace() and " " in s:
        s = s.split(" ", 1)[1]
    if m.end() < len(text) and not text[m.end()].isspace() and " " in s:
        s = s.rsplit(" ", 1)[0]
    return s.strip()


def pass_typographic(text, lex, lang="en"):
    hits = []
    for entry in lex["typographic"]:
        ch = entry["from"]
        n = text.count(ch)
        if not n:
            continue
        hit = {"name": f"{ch} {entry['name']}", "count": n, "to": entry["to"].strip() or "(space)"}
        hits.append(hit)
        if ch == "—":
            if lang != "en":
                # A dash that opens a line is a list marker or a line of
                # dialogue in Russian and Kazakh, not a pause: it stays.
                text = re.sub(r"(?m)^([ \t]*)—", "\\1\x00DASH\x00", text)
                hit["count"] = text.count("—")
                # Quote every dash before it goes: some were grammatical and
                # need a rewrite, not a comma.
                hit["context"] = [_whole_words(text, m).replace("\x00DASH\x00", "—")
                                  for m in re.finditer(r"[^.!?\n]{0,30}—[^.!?\n]{0,30}", text)]
                # "Рынок — это игра" -> "Рынок это игра".
                text = re.sub(r"\s*—\s*(?=это\b)", " ", text, flags=re.IGNORECASE)
            # " word — word " and "word—word" both collapse to a comma + space.
            text = re.sub(r"\s*—\s*", ", ", text)
            text = text.replace("\x00DASH\x00", "—")
            if not hit["count"]:
                hits.remove(hit)
        elif ch == "→":
            # An arrow that ends a line is a carousel slide's "keep swiping"
            # cue, a format, not a tell. Only arrows mid-line become "->".
            hit["count"] = len(re.findall(r"(?m)→(?![ \t]*$)", text))
            text = re.sub(r"(?m)→(?![ \t]*$)", entry["to"], text)
            if not hit["count"]:
                hits.remove(hit)
        elif ch == "–":
            text = re.sub(r"\s*–\s*(?=\d)", "-", text)      # 5–10  -> 5-10
            text = re.sub(r"\s+–\s+", ", ", text)            # used as em dash
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    # A comma inserted before existing punctuation reads wrong.
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*\n", "\n", text)
    return text, hits


def _match_case(src, repl):
    if not repl:
        return repl
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def pass_lexical(text, lex, lang="en"):
    """Replace slop words and phrases. Longest first so phrases win."""
    hits = []
    entries = sorted([e for e in lex["phrases"] + lex["words"] if word_entry_applies(e, lang)],
                     key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        find = entry["find"]
        pattern = entry_pattern(entry)
        found = [m.group(0) for m in pattern.finditer(text)]
        if not found:
            continue
        if entry["replace"] is None:
            # Inflected: a regex would break the grammar. Flag it instead.
            hits.append({"find": find, "replace": None, "count": len(found),
                         "family": entry["family"], "seen": sorted(set(found))[:3],
                         "hint": entry.get("hint", "")})
            continue
        hits.append({"find": find, "replace": entry["replace"] or "(deleted)",
                     "count": len(found), "family": entry["family"]})
        text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
    # Clean up after deletions. Deleting a whole clause leaves orphaned
    # punctuation behind ("system. ." or a line that now opens on a comma),
    # and that reads worse than the slop did.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*(?:[,.;:]+[ \t]*)+", "", text)
    text = re.sub(r"(?m)^[ \t](?=\S)", "", text)       # one space left by a deletion.
                                                      # Deeper indents are deliberate.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)      # an em dash became a comma,
                                                      # then the clause after it went
    text = text.replace("...", "\x00ELL\x00")          # protect real ellipses
    text = re.sub(r"\.\s*\.+", ".", text)
    text = re.sub(r"([!?])\s*\.", r"\1", text)
    text = text.replace("\x00ELL\x00", "...")
    text = re.sub(r"(?m)[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # An em dash that became a comma, followed by a sentence connective, leaves
    # a splice ("is important, also, it's proof"). Promote it to a full stop.
    text = re.sub(r",\s*(also|so|still|basically|in the end)\s*,\s*",
                  lambda m: ". " + m.group(1)[0].upper() + m.group(1)[1:] + ", ", text)
    return text, hits


def scan_structures(text, lex, lang="en"):
    flags = []
    for s in lex["structures"]:
        if not structure_applies(s, lang):
            continue
        try:
            pattern = re.compile(s["regex"], re.MULTILINE)
        except re.error:
            continue
        found = pattern.findall(text)
        if found:
            flags.append({"name": s["name"], "count": len(found), "fix": s["fix"]})
    # Sentence-length uniformity is structural too.
    lens = [len(s.split()) for s in SENT_RE.findall(text) if len(s.split()) > 2]
    if len(lens) >= 4:
        mean = sum(lens) / len(lens)
        var = sum((n - mean) ** 2 for n in lens) / len(lens)
        cv = (var ** 0.5) / mean if mean else 0
        if cv < 0.35:
            flags.append({
                "name": f"Uniform sentence length (variation {cv:.2f})",
                "count": len(lens),
                "fix": "Break one sentence in half. Let another run long. Machines write even.",
            })
    return flags


def restore_capitals(original, text):
    """Deleting an opener leaves the next word lower case.

    Only fix it for writers who capitalise their sentences in the first place:
    a deliberately lower-case voice is a style, not an artefact, and shouting
    over it would be exactly the kind of thing this script exists to stop.
    """
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*([^\W\d_])", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text
    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))\s*([^\W\d_])",
                  lambda m: m.group(0)[:-1] + m.group(1).upper(), text)


def humanize(text, lex, lang=None):
    lang = lang or detect_lang(text)
    raw_for_case = text
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, typo = pass_typographic(text, lex, lang)
    text, lexi = pass_lexical(text, lex, lang)
    text = restore_capitals(raw_for_case, text)
    text = restore_urls(text, urls)
    return text.strip() + "\n", {
        "lang": lang,
        "invisible": inv,
        "typographic": typo,
        "lexical": [h for h in lexi if h["replace"] is not None],
        "flagged": [h for h in lexi if h["replace"] is None],
        "structures": scan_structures(text, lex, lang),
    }


def render_report(report, out=sys.stderr):
    def head(title):
        print(f"\n{title}\n" + "-" * len(title), file=out)

    total = sum(h["count"] for h in report["invisible"]) \
        + sum(h["count"] for h in report["typographic"]) \
        + sum(h["count"] for h in report["lexical"])

    head(f"HUMANIZE REPORT  ·  lang: {report['lang']}")
    print(f"{total} machine artefacts removed, "
          f"{len(report['flagged'])} stock words and "
          f"{len(report['structures'])} structural tells flagged for rewrite", file=out)

    if report["invisible"]:
        head("1. INVISIBLE CHARACTERS")
        for h in report["invisible"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['action']}", file=out)
    if report["typographic"]:
        head("2. TYPOGRAPHY")
        for h in report["typographic"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['to']}", file=out)
            for c in h.get("context", [])[:8]:
                print(f"        was: {c}", file=out)
        if any(h.get("context") for h in report["typographic"]):
            print("        Check each one: a dash that was grammatical needs a rephrase "
                  "(colon, verb, two sentences), not a comma.", file=out)
    if report["lexical"]:
        head("3. SLOP LEXICON")
        for h in report["lexical"]:
            print(f"  {h['count']:>3}x  {h['find']}  -> {h['replace']}   [{h['family']}]", file=out)
    if report["flagged"]:
        head("3b. STOCK WORDS  (inflected, not auto-fixed - rewrite these yourself)")
        for h in report["flagged"]:
            print(f"  {h['count']:>3}x  {h['find']}   [{h['family']}]  seen: "
                  + ", ".join(h["seen"]), file=out)
            if h["hint"]:
                print(f"        {h['hint']}", file=out)
    if report["structures"]:
        head("4. STRUCTURAL TELLS  (not auto-fixed - rewrite these yourself)")
        for h in report["structures"]:
            print(f"  {h['count']:>3}x  {h['name']}\n        {h['fix']}", file=out)
    if not any(v for k, v in report.items() if k != "lang"):
        head("CLEAN")
        print("  Nothing to strip.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Strip the machine fingerprint out of a draft.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("-o", "--out", help="write cleaned text here instead of stdout")
    ap.add_argument("--report", action="store_true", help="print what changed, to stderr")
    ap.add_argument("--json", action="store_true", help="emit {text, report} as JSON")
    ap.add_argument("--lexicon", default=LEX, help="path to slop.json")
    ap.add_argument("--lang", choices=["en", "ru", "kk"], help="skip detection")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lex = load_lexicon(args.lexicon)
    clean, report = humanize(raw, lex, args.lang)

    if args.json:
        print(json.dumps({"text": clean, "report": report}, indent=2, ensure_ascii=False))
        return
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(clean)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    if args.report:
        render_report(report)


if __name__ == "__main__":
    main()
