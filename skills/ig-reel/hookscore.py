#!/usr/bin/env python3
"""
hookscore.py - score the first line of a Reel on the five things strong hooks
have in common, and rank a batch of them against each other.

What this is:  five local heuristics, computed on your machine from the text
alone. They measure properties that hooks which hold attention tend to share -
a length you can say in under three seconds, a concrete marker, something at stake,
the payload at the front rather than the back, and a viewer to aim it at.

What this is NOT:  a view predictor. It was tested against 74 real short-form
hooks, transcribed from the first three seconds of the top eight and bottom
eight performers on five channels. Separating a real hook from a deliberately
bad one it does well: AUC 0.83, and 9 of 10 written-to-be-bad hooks scored
below the real median. Separating a good creator's hits from that same
creator's misses it barely does at all: AUC 0.56, where 0.50 is a coin flip.

So use it for what it measured well. It catches greetings, preambles, hooks
with nothing concrete in them and hooks that take five seconds to say. It will
not tell you which of two decent hooks will travel, and nothing that reads text
can, because that is decided by your face, your edit, your audio and who
Instagram shows it to. Trust the retention graph over this script.

Russian and Kazakh hooks are scored on the same five properties with their own
word lists, and length is timed in syllables rather than words, because a
Kazakh word can carry what takes four English ones. The ru/kk lists were not
part of the 74-hook test above: treat their scores as the same kind of filter,
with less evidence behind it.

Each check returns 0 to 100. Higher is better.

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py --hook "I lost $18,000 on one missing contract."
  python3 hookscore.py --hook "Шарттағы бір тармақ маған 1,8 млн теңгеге түсті."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
  python3 hookscore.py hooks.txt --lang ru    # skip detection
"""

import argparse
import json
import re
import statistics
import sys

WORD_RE = re.compile(r"[\w$%₸'’-]+")
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                       # money, whole
    r"|\b\d[\d,]*(?:\.\d+)?\s?"                      # a figure, with or
    r"(?:%|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"  # without a unit
    r"|days?\b|weeks?\b|months?\b|years?\b)?",
    re.IGNORECASE)
PROPER_RE = re.compile(r"(?<!^)\b[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ][a-zа-яёәғқңөұүһі]{2,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

# Spoken hooks say their numbers out loud. "Zero dollars" and "twenty grand"
# are as concrete as "$0" and "$20,000", and counting only digits missed them.
# "one" and "first" are deliberately absent: they are filler far more often
# than they are a quantity.
SPOKEN_NUMBERS = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
}
MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents",
    "millionaire", "billionaire", "revenue", "profit", "salary", "rent",
}

# Words that put something on the line. A hook with none of these is a
# statement; a hook with one is a reason to keep watching.
STAKES = {
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first",
    "banned", "illegal", "worst", "hate", "hated", "wasted", "waste", "scam",
    "lie", "lied", "lying", "truth", "secret", "hidden", "stole", "stolen",
    "before", "until", "instead", "but", "except", "unless", "problem",
    "risk", "danger", "warning", "regret", "wish", "should", "shouldn't",
    "still", "already", "only", "without", "versus", "vs", "actually",
}

# Openers that spend the first second saying nothing.
WEAK_OPENERS = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "welcome", "today", "basically", "honestly", "look", "listen", "um",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know",
]

# Imperatives that earn the front position.
IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
}

# --- Russian -----------------------------------------------------------------
# Exact forms where a prefix would also catch other words ("сто" is in
# "стоит"), stems where the word inflects and the stem is unambiguous.
RU = {
    "spoken": {
        "ноль", "нуля", "два", "две", "двух", "три", "трех", "трёх", "четыре", "четырех",
        "пять", "пяти", "шесть", "шести", "семь", "семи", "восемь", "восьми", "девять",
        "девяти", "десять", "десяти", "одиннадцать", "двенадцать", "пятнадцать",
        "двадцать", "двадцати", "тридцать", "тридцати", "сорок", "пятьдесят",
        "шестьдесят", "семьдесят", "восемьдесят", "девяносто", "сто", "ста", "двести",
        "триста", "пятьсот", "тысяча", "тысячи", "тысяч", "тысячу", "миллион",
        "миллиона", "миллионов", "миллиард", "миллиарда", "миллиардов", "полтора",
        "полторы", "половина", "половину", "вдвое", "втрое", "дважды", "трижды",
        "десятки", "сотни", "сотен",
    },
    "money": {
        "тенге", "тг", "₸", "рублей", "рубля", "руб", "долларов", "доллара", "баксов",
        "сумов", "сум", "выручка", "выручку", "выручки", "прибыль", "прибыли",
        "зарплата", "зарплату", "зарплаты", "аренда", "аренду", "оборот", "млн", "тыс",
        "млрд", "лям", "ляма", "лямов", "косарь", "процентов", "процента", "бюджет",
    },
    "stakes": {
        "не", "нет", "ни", "никто", "ничего", "никогда", "нельзя", "хватит", "стоп", "без",
        "вместо", "кроме", "но", "до", "пока", "только", "уже", "еще", "ещё", "против",
        "зря", "хуже", "раньше", "первый", "первая", "первые", "первых", "правда", "ложь", "минус",
    },
    "stake_stems": (
        "ошиб", "потер", "провал", "увол", "удал", "бесплат", "заплат", "сэконом", "запрещ",
        "худш", "ненавид", "ненавиж", "обман", "секрет", "скрыт", "скрыва", "украл", "укра",
        "проблем", "риск", "опасн", "предупрежд", "сожале", "жалею", "слил", "сломал",
        "разор", "банкрот", "штраф", "долг", "убыт", "потрат", "переплат", "стоил",
        "обошл", "врут", "врал", "правд", "никогд", "нельз", "провер",
    ),
    "weak": [
        "итак", "так", "ну", "ок", "окей", "привет", "всем привет", "всем", "здравствуйте",
        "друзья", "ребята", "сегодня", "в общем", "короче", "честно говоря", "слушайте",
        "давайте", "давай", "я хотел", "я хотела", "я хочу", "хочу", "одна из", "один из",
        "вы когда", "ты когда", "знаете", "это", "есть", "как вы", "многие", "в этом",
        "в сегодняшнем", "в современном", "добро", "когда речь", "вот", "кстати",
    ],
    "imperatives": {
        "хватит", "стоп", "перестань", "перестаньте", "забирай", "забирайте", "укради",
        "копируй", "скопируй", "удали", "удалите", "попробуй", "попробуйте", "смотри",
        "посмотри", "читай", "прочитай", "сохрани", "сохраните", "сохраняй", "используй",
        "сделай", "делай", "напиши", "пиши", "отправь", "возьми", "начни", "начните",
        "брось", "бросьте", "никогда", "всегда", "проверь", "проверьте", "запомни",
        "забудь", "забудьте", "не",
    },
    "you": re.compile(r"\b(?:ты|тебя|тебе|тобой|твой|твоя|твоё|твое|твои|твоих|твоим|вы|вас"
                      r"|вам|вами|ваш|ваша|ваше|ваши|ваших)\b|\b\w+(?:ешь|ёшь|ишь)\b",
                      re.IGNORECASE),
    "me": re.compile(r"\b(?:я|мне|меня|мой|моя|моё|мое|мои|мы|нам|нас|наш|наша|наше|наши)\b",
                     re.IGNORECASE),
}

# --- Kazakh ------------------------------------------------------------------
# Kazakh glues case and person onto the word, so numbers match base + a known
# suffix ("мыңға", "екіден"), and negation lives in the verb ("жасама",
# "айтпайды"), which a word list cannot see. "онда" and "оны" are pronouns.
KK_NUMBER_BASES = (
    "нөл", "екі", "үш", "төрт", "бес", "алты", "жеті", "сегіз", "тоғыз", "он",
    "жиырма", "отыз", "қырық", "елу", "алпыс", "жетпіс", "сексен", "тоқсан", "жүз",
    "мың", "миллион", "миллиард", "жарты", "екеу", "үшеу", "төртеу", "бесеу",
)
KK_NUMBER_SUFFIXES = {
    "", "ға", "ге", "қа", "ке", "на", "не", "а", "е", "нан", "нен", "дан", "ден", "тан",
    "тен", "да", "де", "та", "те", "нда", "нде", "ды", "ді", "ты", "ті", "ны", "ні",
    "ның", "нің", "дың", "дің", "тың", "тің", "мен", "бен", "пен", "ыншы", "інші",
    "ншы", "нші", "еу", "ау", "дай", "дей", "тай", "тей",
}
KK_NOT_NUMBERS = {"онда", "оны", "оның", "онан", "оған", "ондай", "ода", "оде"}
KK = {
    "spoken": set(),
    "money": {
        "теңге", "тенге", "теңгеге", "теңгеден", "теңгені", "тг", "₸", "доллар", "табыс",
        "табысы", "пайда", "пайдасы", "жалақы", "айлық", "жалдау", "айналым", "млн", "мың",
        "млрд", "пайыз", "бюджет",
    },
    "stakes": {
        "жоқ", "емес", "ешқашан", "ешкім", "ешнәрсе", "ештеңе", "тоқта", "тоқтат", "бірақ",
        "тек", "әлі", "бұрын", "дейін", "орнына", "түсті", "онсыз", "бекер", "тегін", "бірінші", "алғашқы",
        "шын", "шындық", "құпия", "өтірік", "қате", "қателік", "мәселе", "қарсы",
    },
    "stake_stems": (
        "қате", "жоғалт", "шығын", "тұрды", "сындыр", "сәтсіз", "күйре", "өшір", "төле",
        "үнемде", "тыйым", "нашар", "алдад", "алдан", "өтірік", "жасыр", "ұрла", "проблем",
        "мәселе", "тәуекел", "қауіп", "ескерт", "өкін", "айыппұл", "қарыз", "банкрот",
        "тегін", "доғар", "құпия", "шындық",
    ),
    "negation": re.compile(r"[^\W\d_]{2,}(?:ма|ме|ба|бе|па|пе)(?:ңыз|ңіз|ңдар|ңдер|ймын|ймін"
                           r"|йды|йді|йсың|йсің|йсыз|йсіз|ған|ген|ды|ді|дым|дім|дық|дік|с"
                           r"|сын|сін)?"),
    "weak": [
        "сонымен", "жә", "ал енді", "ал", "енді", "сәлем", "сәлеметсіздер", "сәлеметсіз",
        "армысыздар", "армысыз", "қайырлы", "достар", "бүгін", "бүгінгі", "негізі",
        "шынымды айтсам", "тыңдаңыз", "мен айтайын", "айтқым келеді", "бұл видеода",
        "қазіргі", "бәріңізге", "жалпы", "қысқасы", "міне",
    ],
    "imperatives": {
        "тоқта", "тоқтат", "доғар", "алыңыз", "көшір", "көшіріңіз", "өшір", "өшіріңіз",
        "қара", "қараңыз", "оқы", "оқыңыз", "сақта", "сақтаңыз", "қолдан", "қолданыңыз",
        "жаса", "жасаңыз", "жаз", "жазыңыз", "жібер", "жіберіңіз", "баста", "бастаңыз",
        "таста", "тастаңыз", "ешқашан", "әрқашан", "тексер", "тексеріңіз", "ұмыт",
        "ұмытыңыз", "көр", "көріңіз", "тыңда",
    },
    "you": re.compile(r"\b(?:сен|сенің|саған|сені|сенде|сенен|сіз|сіздің|сізге|сізді|сізде"
                      r"|сізден|сендер|сіздер|сіздерге|сендерге)\b"
                      r"|\b[^\W\d_]{2,}(?:сың|сің|ңыз|ңіз|ыңыз|іңіз|саң|сең|ңдар|ңдер)\b",
                      re.IGNORECASE),
    "me": re.compile(r"\b(?:менің|маған|мені|менде|біз|біздің|бізге|бізді)\b"
                     r"|\b[^\W\d_]{2,}(?:мын|мін|бын|бін|пын|пін|дым|дім|тым|тім|мыз|міз"
                     r"|дық|дік|тық|тік)\b", re.IGNORECASE),
}

VOWELS = set("аеёиоуыэюяәөұүіАЕЁИОУЫЭЮЯӘӨҰҮІ")
ABBREV_SYLLABLES = {"млн": 3, "млрд": 3, "тыс": 2, "тг": 2, "₸": 2, "%": 2}
SYLLABLES_PER_SEC = 5.2      # Russian and Kazakh, said briskly to camera
KK_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
KK_WORDS = {"бұл", "және", "үшін", "емес", "жоқ", "ешкім", "керек", "болады", "деп",
            "мен", "сен", "сіз", "біз", "олар", "қалай", "неге", "қашан", "қандай",
            "бар", "бір", "ең", "тек", "бірақ", "енді", "осы", "сол", "мына", "кім"}
RU_WORDS = {"и", "в", "на", "что", "это", "как", "с", "по", "я", "ты", "вы", "мы",
            "он", "она", "они", "у", "к", "за", "из", "от", "для", "так", "все",
            "но", "а", "или", "если", "то", "бы", "же", "ли", "только", "уже",
            "когда", "где"}

DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"),
     "Greeting. Nobody came to the feed to be greeted."),
    (HASHTAG_RE,
     "Hashtag in the hook. Hashtags belong at the bottom of the caption, if anywhere."),
    (EMOJI_RE,
     "Emoji in the hook. On-screen text at hook size has room for words or for an emoji, not both."),
    (re.compile(r"(?i)^\s*(?:стоп[,!.]?\s*(?:не\s+)?листай|не листай|не пролистывай|остановись"
                r"|(?:тоқта[,!.]?\s*)?(?:парақтама|айналдырма|өткізіп\s+жіберме))"),
     "Начинается с «не листай». Просьба о внимании доказывает, что ты его не заработал."),
    (re.compile(r"(?i)\b(?:в этом (?:видео|ролике|рилсе)|в сегодняшнем (?:видео|ролике)"
                r"|сегодня я (?:расскажу|покажу)|я (?:покажу|расскажу) вам"
                r"|бұл (?:видеода|роликте|рилсте)|бүгінгі (?:видеода|роликте)"
                r"|бүгін (?:мен\s+)?(?:айтып\s+беремін|көрсетемін))\b"),
     "Преамбула «в этом видео». Удали и начни с результата."),
    (re.compile(r"(?i)^\s*(?:всем привет|привет|здравствуйте|добрый (?:день|вечер)|доброе утро"
                r"|салам|друзья[,!]|ребята[,!]|добро пожаловать"
                r"|сәлем|сәлеметсіз|армысыз|ассалаумағалейкум|қайырлы (?:күн|таң|кеш)"
                r"|достар[,!])"),
     "Приветствие. В ленту никто не пришел, чтобы с ним поздоровались."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def detect_lang(text):
    """'en', 'ru' or 'kk'. Same rule as ig-human/humanize.py."""
    text = re.sub(r"https?://\S+|www\.\S+|[@#]\w+", " ", text)
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    if not cyr or cyr < lat:
        return "en"
    toks = re.findall(r"[^\W\d_]+", text.lower())
    kk = sum(1 for c in text if c in KK_LETTERS) + 2 * sum(1 for t in toks if t in KK_WORDS)
    ru = 2 * sum(1 for t in toks if t in RU_WORDS)
    return "kk" if kk > ru else "ru"


def words(text):
    # "$18,000" and "18 000" are one word when spoken, so they are one word here too.
    text = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def syllables(text):
    """Vowels per word, plus a rough count for digits and abbreviations said aloud."""
    n = 0
    for w in words(text):
        low = w.lower()
        if low in ABBREV_SYLLABLES:
            n += ABBREV_SYLLABLES[low]
            continue
        digits = sum(1 for c in w if c.isdigit())
        n += sum(1 for c in w if c in VOWELS) + (min(8, max(1, round(digits * 1.7))) if digits else 0)
    return n


def _is_kk_number(tok):
    if tok in KK_NOT_NUMBERS:
        return False
    return any(tok.startswith(b) and tok[len(b):] in KK_NUMBER_SUFFIXES for b in KK_NUMBER_BASES)


def _lists(lang):
    return {"ru": RU, "kk": KK}.get(lang)


def is_spoken_number(tok, lang):
    if lang == "en":
        return tok in SPOKEN_NUMBERS
    if lang == "kk":
        return _is_kk_number(tok)
    return tok in RU["spoken"]


def is_money(tok, lang):
    return tok in MONEY_WORDS if lang == "en" else tok in _lists(lang)["money"]


def is_stake(tok, lang):
    if lang == "en":
        return tok in STAKES
    L = _lists(lang)
    if tok in L["stakes"] or any(tok.startswith(s) for s in L["stake_stems"]):
        return True
    return bool(lang == "kk" and KK["negation"].fullmatch(tok))


def check_length(text, lang="en"):
    """A hook has to land before the thumb moves. Roughly two seconds."""
    w = words(text)
    n = len(w)
    chars = len(text.strip())
    if lang == "en":
        secs = n / 2.75                      # ~165 words per minute, spoken
        if 5 <= n <= 12:
            score = 100.0
        elif n < 5:
            score = clamp(100 - (5 - n) * 20)
        else:
            score = clamp(100 - (n - 12) * 11)
        if chars > 60:                       # two lines of big on-screen text
            score -= 12
        return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-12 words)"
    # Russian and Kazakh words run long, so time the syllables instead. The
    # window matches the English one: 5 to 12 words at 165 wpm is 1.8 to 4.4s.
    syl = syllables(text)
    secs = syl / SYLLABLES_PER_SEC
    if 1.4 <= secs <= 4.2:
        score = 100.0
    elif secs < 1.4:
        score = clamp(100 - (1.4 - secs) * 50)
    else:
        score = clamp(100 - (secs - 4.2) * 30)
    if chars > 70:                           # Cyrillic sets wider on screen
        score -= 12
    return clamp(score), (f"{n} words, {syl} syllables, {chars} chars, ~{secs:.1f}s spoken "
                          f"(want under ~4s)")


def check_specificity(text, lang="en"):
    """One concrete thing beats three abstract ones."""
    flat = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)
    nums = [n.strip() for n in NUMBER_RE.findall(flat) if n.strip()]
    propers = set(PROPER_RE.findall(text))
    low = [w.lower().strip("'’") for w in words(text)]
    spoken = [w for w in low if is_spoken_number(w, lang) or is_money(w, lang)]
    hits = len(nums) + len(propers) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(propers)[:2] + spoken[:2])
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def check_stakes(text, lang="en"):
    """Tension, cost, negation. Something the viewer might lose."""
    w = [x.lower().strip("'’") for x in words(text)]
    hits = [x for x in w if is_stake(x, lang)]
    markers = sorted(set(hits))
    if re.search(r"\$\s?\d|\d\s?₸|₸\s?\d", text):
        markers.append("a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line")
    return clamp(score), detail


def check_frontload(text, lang="en"):
    """The interesting word cannot be in position nine."""
    w = words(text)
    if not w:
        return 0.0, "empty"
    low = [x.lower().strip("'’") for x in w]
    opener = " ".join(low[:2])
    penalty = 0
    hit_opener = None
    weak_list = WEAK_OPENERS if lang == "en" else _lists(lang)["weak"]
    for weak in weak_list:
        # English keeps its original prefix match; ru/kk match whole words,
        # because "это" would otherwise catch "этот".
        hit = (opener.startswith(weak) or low[0] == weak) if lang == "en" else \
            (opener + " ").startswith(weak + " ")
        if hit:
            penalty, hit_opener = 30, weak
            break
    payload = None
    for i, token in enumerate(low):
        if (is_stake(token, lang) or is_spoken_number(token, lang) or is_money(token, lang)
                or NUMBER_RE.match(w[i]) or (i and PROPER_RE.match(w[i]))):
            payload = i
            break
    if payload is None:
        base = 30.0
        where = "no payload word anywhere in the line"
    elif payload <= 3:
        base = 100.0
        where = f"payload at word {payload + 1}"
    elif payload <= 6:
        base = 70.0
        where = f"payload at word {payload + 1}, could move forward"
    else:
        base = 40.0
        where = f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def check_address(text, lang="en"):
    """Aimed at one viewer, or floating in the air."""
    low = text.lower()
    w = [x.lower().strip("'’") for x in words(text)]
    if lang == "en":
        if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
            return 100.0, "speaks to the viewer"
        if w and w[0] in IMPERATIVES:
            return 90.0, f"imperative opener (\"{w[0]}\")"
        if re.search(r"\b(i|my|me|we|our)\b", low):
            return 70.0, "first person, no viewer named"
        return 35.0, "third person, nobody in the room"
    L = _lists(lang)
    if L["you"].search(low):
        return 100.0, "speaks to the viewer"
    # Kazakh puts the verb last, so an imperative can close the hook as well.
    ends = ([w[0]] + ([w[-1]] if lang == "kk" and len(w) > 1 else [])) if w else []
    imp = next((x for x in ends if x in L["imperatives"]
                or (lang == "kk" and re.fullmatch(r"[^\W\d_]{2,}(?:ма|ме|ба|бе|па|пе)", x))), None)
    if imp:
        return 90.0, f"imperative (\"{imp}\")"
    if L["me"].search(low):
        return 70.0, "first person, no viewer named"
    return 35.0, "third person, nobody in the room"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text, lang=None):
    lang = lang or detect_lang(text)
    results = {
        "LENGTH": check_length(text, lang),
        "SPECIFICITY": check_specificity(text, lang),
        "STAKES": check_stakes(text, lang),
        "FRONTLOAD": check_frontload(text, lang),
        "ADDRESS": check_address(text, lang),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook, same logic as detect.py: one bad
    # property is enough for the thumb to keep moving.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        weakest: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nShoot the top one. If the top one is under 50, none of these are the hook.\n",
          file=out)


def main():
    ap = argparse.ArgumentParser(description="Score a Reel hook on five properties.")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--lang", choices=["en", "ru", "kk"], help="skip detection")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line, args.lang)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return

    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0], args.lang)
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))

    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
