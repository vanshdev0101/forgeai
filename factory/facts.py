"""Deterministic fact matching, shared by the eval generator (is this fact really in its source
passage?) and the judge (does the answer state it?). One normaliser for both, so they cannot
disagree about what "the same fact" means.

Numbers must match exactly after normalisation (2,500 == 2500, 2.0 == 2, 2,27,500 == 227500); words
may drift a little (80% of content words). Anything this misses goes to the LLM judge, whose answer is
then checked against these same rules.
"""
import re

NUM = re.compile(r"\d+(?:\.\d+)?")
_WORDNUM = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_WORDNUM.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90", "hundred": "100"})
# Words that carry no checkable content: attribution and courtesy.
_FILLER = set("according policy policies document documents documentation note please per states stated mentioned "
              "provided guidance general always feel free reach relevant team unclear happy help questions also "
              "however based your you our this that these those there here will would may can "
              # function words; deliberately NOT "not"/"no": a negation flip changes the meaning
              "the and for with are was were has have had from into its it's been being which who".split())


def _canon_num(n):
    f = float(n)
    return str(int(f)) if f == int(f) else repr(f)


def norm(text):
    t = str(text).lower().replace("_", " ")  # CSV columns: annual_leave_days -> annual leave days
    # 2,500 / 2,27,500 -> digits only. Not plain spaces: "grade 3 24 days" must not become "324".
    t = re.sub(r"(?<=\d)[, ](?=\d{2,3}\b)", "", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)  # 31st -> 31
    t = re.sub(r"[^\w\s.%]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # keep decimal points, drop sentence dots
    return " ".join(_WORDNUM.get(w, w) for w in t.split())


def _stem(w):
    for suf in ("ing", "ed", "s"):  # not "es": lapses -> laps would miss lapse
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def numbers(text):
    return {_canon_num(n) for n in NUM.findall(norm(text))}


def content_words(text, drop_filler=False):
    return [_stem(w) for w in norm(text).split() if len(w) > 2 and not NUM.fullmatch(w)
            and not (drop_filler and w in _FILLER)]


def fact_in_text(fact, text, word_share=0.8):
    """True if `text` states `fact`: exact normalised substring, or every number in the fact present
    and most of its (lightly stemmed) content words present."""
    f, t = norm(fact), norm(text)
    if not f:
        return False
    if f in t:
        return True
    fnums = numbers(fact)
    if fnums - numbers(text):
        return False
    words = content_words(fact)
    if not words:
        return bool(fnums)
    tw = {_stem(w) for w in t.split()}
    return sum(w in tw for w in words) / len(words) >= word_share


def is_checkable_claim(claim, context):
    """Filter for the LLM's 'unsupported claims'. Drops (a) courtesy/attribution filler: no number and
    fewer than 2 content words that occur in the context; (b) near-verbatim restatements: every number
    supported and every non-filler content word present in the context. Anything else stays for the
    report, including modality flips ('may' -> 'must'), which change words this cannot vouch for."""
    words = content_words(claim, drop_filler=True)
    ctx = {_stem(w) for w in norm(context).split()}
    in_ctx = [w for w in words if w in ctx]
    nums = numbers(claim)
    if not nums and len(in_ctx) < 2:
        return False
    if not (nums - numbers(context)) and words and len(in_ctx) == len(words):
        return False
    return True


def span_supports(span, fact, answer):
    """Accept an LLM judge's 'yes' only if its quoted span is really in the answer and carries
    every number the fact has. A judge that says yes to a changed number is overruled."""
    if not span or norm(span) not in norm(answer):
        return False
    return not (numbers(fact) - numbers(span))
