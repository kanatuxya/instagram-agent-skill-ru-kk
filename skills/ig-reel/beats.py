#!/usr/bin/env python3
"""
beats.py - turn a Reel script into a timed beat sheet before you record it.

Estimates how long each line takes to say, stacks them into timecodes, and
flags the four things that kill a Reel in the edit: a hook that runs past the
three-second mark, a beat long enough for the viewer to leave, a run of lines
with nothing concrete in them, and a total length that does not match what you
said you were making.

The timings are an estimate from word count at a words-per-minute rate. They
are close enough to plan an edit and not a substitute for recording it. Set
your own rate with --wpm once you have timed yourself reading a script out
loud: most people land between 150 and 200, and the default here is 165.

Russian and Kazakh scripts are timed in syllables instead (vowels per word),
at 5.2 a second by default, because word counts lie there: one Kazakh word can
take as long to say as three English ones. Set your own with --sps, or force
word timing with --wpm.

Usage
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --wpm 185 --target 45
  python3 beats.py script.txt --sps 4.8 --target 30     # ru/kk, your own pace
  pbpaste | python3 beats.py -
  python3 beats.py script.txt --json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hookscore import (SYLLABLES_PER_SEC, detect_lang, is_money,  # noqa: E402
                       is_spoken_number, syllables)

WORD_RE = re.compile(r"[\w$%₸'’-]+")
SENT_RE = re.compile(r"[^.!?]+[.!?]*")
CONCRETE_RE = re.compile(r"\$\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ][a-zа-яёәғқңөұүһі]{2,}\b",
                         re.MULTILINE)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "that", "this", "it", "is", "are", "was", "were", "be", "been",
    "you", "your", "i", "my", "me", "we", "our", "they", "them", "he", "she",
    "so", "just", "not", "no", "do", "did", "does", "have", "has", "had",
    "will", "can", "at", "as", "by", "from", "out", "up", "off", "one", "all",
    # Russian
    "и", "в", "во", "не", "на", "я", "что", "с", "со", "как", "а", "то", "все", "всё",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "её", "мне", "было", "вот", "от", "меня", "еще", "ещё", "нет", "о",
    "из", "ему", "теперь", "когда", "даже", "ну", "ли", "если", "уже", "или", "ни",
    "быть", "был", "до", "вас", "там", "потом", "себя", "они", "тут", "где", "есть",
    "для", "мы", "тебя", "их", "чем", "сам", "без", "кто", "этот", "это", "мой", "наш",
    # Kazakh
    "және", "мен", "бен", "пен", "бұл", "сол", "осы", "ол", "біз", "сен", "сіз", "де",
    "та", "те", "ма", "ме", "үшін", "деп", "бір", "бар", "жоқ", "емес", "ал", "бірақ",
    "енді", "тек", "әр", "ең", "қалай", "кім", "менің", "сенің", "оның", "біздің",
    "сіздің", "олар", "ғой", "қой", "ғана", "тағы", "тіпті", "өте",
}

HOOK_WINDOW = 3.0        # seconds. Past this, the thumb has already decided.
MAX_BEAT = 4.0           # seconds on one idea with no change on screen.
ABSTRACT_RUN = 3         # beats in a row with nothing checkable in them.


def words(text):
    # "$18,000" and "18 000" are one word when spoken, so they are one word here too.
    text = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def pretty(token):
    """Put the thousands separator back for display."""
    return re.sub(r"(\d)(?=(\d{3})+$)", r"\1,", token)


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def loop_key(word):
    """Cyrillic inflects ("клиент" / "клиенту"), so loops compare stems there."""
    w = word.lower()
    return w[:5] if len(w) > 5 and re.search(r"[а-яёәғқңөұүһі]", w) else w


def pace(lang, wpm=None, sps=SYLLABLES_PER_SEC):
    """(seconds-for-text, units per second, unit name, label for the header)."""
    if wpm or lang == "en":
        wpm = wpm or 165
        wps = wpm / 60.0
        return (lambda t: len(words(t)) / wps), wps, "words", f"{wpm} wpm"
    return (lambda t: syllables(t) / sps), sps, "syllables", f"{sps} syl/s"


def concrete(text, lang):
    n = len(CONCRETE_RE.findall(text))
    if lang != "en":
        # "пять часов", "екі жыл": spoken numbers are as checkable as digits.
        n += sum(1 for w in words(text)
                 if is_spoken_number(w.lower(), lang) or is_money(w.lower(), lang))
    return n


def split_beats(raw, dur):
    """One line is one beat, unless a line is too long to be one."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if dur(line) <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # Long paragraph: break it at sentence ends so the timings mean
        # something, and let the report say it was split.
        parts = [p.strip() for p in SENT_RE.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and dur(candidate) > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, wpm=None, target=None, sps=SYLLABLES_PER_SEC, lang=None):
    lang = lang or detect_lang(raw)
    dur_of, per_sec, unit, rate = pace(lang, wpm, sps)
    beats = split_beats(raw, dur_of)
    if not beats:
        return None

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(words(text))
        dur = dur_of(text)
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "words": n,
            "text": text,
            "concrete": concrete(text, lang),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # Label the structural positions a Reel is actually built around.
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "HOOK" else "HOOK/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "MID"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"hook runs {rows[0]['dur']:.1f}s, past the {HOOK_WINDOW:.0f}s mark")
        notes.append(f"Beat 1 takes {rows[0]['dur']:.1f}s to say. Cut it to "
                     f"{int(HOOK_WINDOW * per_sec)} {unit} or fewer, or the hook lands after "
                     "the decision has been made.")
    if rows[0]["concrete"] == 0:
        notes.append("Beat 1 has no number and no name in it. Hooks without something "
                     "checkable are the ones that get scrolled.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f}s on one beat")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Beat(s) {', '.join(map(str, long_beats))} run past {MAX_BEAT:.0f}s. "
                     "Either split the line or change what is on screen inside it. "
                     "A static frame is where people leave.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"Beats {start}-{r['n']} have nothing concrete in them. "
                             "Put a number, a name or a price in one of them.")
        else:
            run, start = 0, None

    # Does the last line hand you back to the first one?
    first = {loop_key(w): w.lower() for w in words(rows[0]["text"]) if w.lower() not in STOPWORDS}
    last = {loop_key(w) for w in words(rows[-1]["text"]) if w.lower() not in STOPWORDS}
    loop = sorted(pretty(first[k]) for k in first.keys() & last)
    if loop:
        notes.append(f"Loops: the last beat repeats \"{', '.join(loop[:3])}\" from the hook. "
                     "Second watches are free reach.")
    else:
        notes.append("No loop. The last beat shares no word with the hook, so the video "
                     "ends flat. Echoing one word from beat 1 is the cheapest replay you get.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Length is on target ({total:.1f}s against {target}s).")
        elif delta > 0:
            notes.append(f"{delta:.1f}s over target. Cut about {int(delta * per_sec)} {unit}.")
        else:
            notes.append(f"{-delta:.1f}s under target. Either add {int(-delta * per_sec)} {unit} "
                         "or shoot it short. Short is usually right.")

    return {
        "wpm": wpm or (165 if unit == "words" else None), "rate": rate, "lang": lang,
        "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "beats": rows,
        "notes": notes,
    }


def render(a, out=sys.stdout):
    head = (f"BEAT SHEET  ·  {a['total_words']} words  ·  ~{a['total_seconds']:.1f}s "
            f"at {a['rate']}" + (f"  ·  target {a['target']}s" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<8}" if r["label"] else " " * 8
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}s  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}  {'':<8}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Time a Reel script into a beat sheet.")
    ap.add_argument("input", nargs="?", default="-", help="script file, or - for stdin")
    ap.add_argument("--wpm", type=float, help="speaking rate in words (default 165, English)")
    ap.add_argument("--sps", type=float, default=SYLLABLES_PER_SEC,
                    help=f"syllables per second for ru/kk (default {SYLLABLES_PER_SEC})")
    ap.add_argument("--lang", choices=["en", "ru", "kk"], help="skip detection")
    ap.add_argument("--target", type=float, help="target length in seconds")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    a = analyse(raw, wpm=args.wpm, target=args.target, sps=args.sps, lang=args.lang)
    if not a:
        print("empty script", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
