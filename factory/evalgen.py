"""Requirement 4: the eval generator.

Builds the test set from the documents themselves. The factory model only *phrases* questions;
what counts as correct is checked or computed in code:
  answerable / multi_doc / ambiguous  key facts must appear verbatim-ish in the source passage
  calculator                          expected number computed from the model's expression, whose
                                      numbers must come from the passage or the question
  csv_lookup                          expected value read from the CSV cell itself (no LLM)
  out_of_scope / ungroundable         must be refused
Prompts live in prompts/eval_*.md.
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

from factory.common import ask_json, log
from factory.facts import NUM, content_words, fact_in_text, numbers
from runtime import tools

TARGETS = {"answerable": 10, "multi_doc": 3, "ambiguous": 3, "unrelated": 2, "calculator": 2, "csv_lookup": 2}
MIN_CASES = 20
TEMPERATURE = 0.6  # variety between cases; the fixed seed keeps a run reproducible


def _spread(chunks):
    """Round-robin over documents so every document is tested, not just the first one."""
    by_doc = defaultdict(list)
    for c in chunks:
        by_doc[c["doc"]].append(c)
    out = []
    while any(by_doc.values()):
        for d in sorted(by_doc):
            if by_doc[d]:
                out.append(by_doc[d].pop(0))
    return out


MAX_FACT_WORDS = 8
# Numeric core of a sentence: optional currency, a number (not inside a code like G5), and a unit that
# isn't a function word. "allowance of INR 2,500 for domestic travel" -> "INR 2,500"; "up to 10 days" -> "10 days".
_NUMPHRASE = re.compile(r"(?:(?:INR|USD|EUR|GBP|Rs\.?|\$|€|£)\s?)?(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?"
                        r"(?:\s?%|\s+(?!(?:for|and|of|to|in|on|or|the|a|an|with|per|by|from|may|is|are)\b)[A-Za-z]+)?")


def _shorten(fact):
    """A sentence-long 'fact' (the 9b model often copies whole sentences) is replaced by its numeric
    phrases; a long fact with no number is dropped."""
    if len(fact.split()) <= MAX_FACT_WORDS:
        return [fact]
    return [m.group(0).strip() for m in _NUMPHRASE.finditer(fact)]


def _verified(facts, passage, reference=None):
    """Keep facts that are (1) short (long ones shortened to their numeric core), (2) really in the
    source passage and (3) part of the generator's own reference answer. (3) is a relevance check: a
    fact the generator's answer doesn't mention isn't what its question asks (live: a flight-class
    question listed the daily allowance as its facts)."""
    out = []
    for raw in facts:
        raw = raw.strip().strip('"').strip() if isinstance(raw, str) else ""
        for f in _shorten(raw) if raw else []:
            if (f not in out and fact_in_text(f, passage)
                    and (reference is None or fact_in_text(f, reference))):
                out.append(f)
    return out


def _q_ok(o, *keys):
    if not isinstance(o, dict) or not isinstance(o.get("question"), str) or len(o["question"].split()) < 3:
        return "need a 'question' string of at least 3 words"
    for k in keys:
        if not isinstance(o.get(k), list):
            return f"need '{k}' as a list of strings"
    return None


DUP_SIMILARITY = 0.8


def _similar(a, b):
    wa, wb = set(content_words(a, drop_filler=True)), set(content_words(b, drop_filler=True))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= DUP_SIMILARITY


def _new(cases, question):
    """Not empty and not a near-duplicate (live: 'how many can an employee carry over' and 'how many
    can I carry over' were both kept)."""
    return bool(question.strip()) and not any(_similar(question, c["question"]) for c in cases)


def _bool_check(*keys):
    def check(o):
        if not isinstance(o, dict) or not all(isinstance(o.get(k), bool) for k in keys):
            return "need JSON with boolean " + ", ".join(keys)
        return None
    return check


def answerable(req, pool, n, dropped):
    """One question per passage per pass; extra passes with an avoid-list when the corpus is small."""
    cases, asked = [], defaultdict(list)
    for attempt in range(n * 3):
        if len(cases) >= n or not pool:
            break
        c = pool[attempt % len(pool)]
        avoid = ("Do NOT ask any of these again; ask about something else in the passage:\n" +
                 "\n".join(f"- {q}" for q in asked[c["id"]]) + "\n") if asked[c["id"]] else ""
        o = ask_json("eval_answerable", check=lambda o: _q_ok(o, "key_facts"), temperature=TEMPERATURE,
                     audience=req["audience"], summary=req["summary"], chunk_id=c["id"], passage=c["text"],
                     avoid=avoid)
        asked[c["id"]].append(o["question"])
        facts = _verified(o["key_facts"], c["text"], str(o.get("answer") or ""))
        if not facts:
            dropped.append({"type": "answerable", "question": o["question"], "chunk": c["id"],
                            "why": f"no key fact of {o['key_facts']} is short, in the source passage and in "
                                   "its own reference answer"})
            continue
        if _new(cases, o["question"]):
            cases.append({"type": "answerable", "question": o["question"].strip(),
                          "expected": {"refuse": False, "key_facts": facts, "source_docs": [c["doc"]],
                                       "source_chunks": [c["id"]]},
                          "origin": {"prompt": "eval_answerable", "reference_answer": o.get("answer", "")}})
    return cases


def multi_doc(req, pool, n, dropped):
    """Pairs of passages from different documents (different chunks if there is only one document)."""
    pairs, docs = [], sorted({c["doc"] for c in pool})
    if len(docs) > 1:
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                if a["doc"] != b["doc"]:
                    pairs.append((a, b))
    else:
        pairs = list(zip(pool, pool[1:]))
    cases, asked = [], defaultdict(list)
    for attempt in range(n * 4):  # cycle pairs: a 3-document corpus has only 3 pairs
        if len(cases) >= n or not pairs:
            break
        a, b = pairs[attempt % len(pairs)]
        key = (a["id"], b["id"])
        avoid = ("Do NOT ask any of these again:\n" + "\n".join(f"- {q}" for q in asked[key]) + "\n"
                 if asked[key] else "")
        o = ask_json("eval_multi", check=lambda o: _q_ok(o, "facts_a", "facts_b"), temperature=TEMPERATURE,
                     audience=req["audience"], summary=req["summary"], id_a=a["id"], passage_a=a["text"],
                     id_b=b["id"], passage_b=b["text"], avoid=avoid)
        asked[key].append(o["question"])
        ref = str(o.get("answer") or "")
        fa, fb = _verified(o["facts_a"], a["text"], ref), _verified(o["facts_b"], b["text"], ref)
        if not (fa and fb):
            dropped.append({"type": "multi_doc", "question": o["question"], "chunks": [a["id"], b["id"]],
                            "why": f"needs a verified fact from each passage; proposed A={o['facts_a']} "
                                   f"B={o['facts_b']}, kept A={fa} B={fb}"})
            continue
        if _new(cases, o["question"]):
            cases.append({"type": "multi_doc", "question": o["question"].strip(),
                          "expected": {"refuse": False, "key_facts": fa + fb,
                                       "source_docs": sorted({a["doc"], b["doc"]}),
                                       "source_chunks": [a["id"], b["id"]]},
                          "origin": {"prompt": "eval_multi", "reference_answer": o.get("answer", "")}})
    return cases


def ambiguous(base, n, dropped):
    """Informal rewrites of answerable cases. An independent check confirms each still asks for the
    same information (live: 'domestic work travel' was rewritten as 'working at home')."""
    cases = []
    for b in base[: n * 2]:
        if len(cases) >= n:
            break
        o = ask_json("eval_ambiguous", check=_q_ok, temperature=TEMPERATURE, question=b["question"])
        rewrite = o["question"].strip()
        same = ask_json("eval_check_rewrite", check=_bool_check("same_information"),
                        original=b["question"], rewrite=rewrite)
        if not same["same_information"]:
            dropped.append({"type": "ambiguous", "question": rewrite, "rewrite_of": b["question"],
                            "why": f"rewrite changed the meaning: {same.get('reason', '')}"})
            continue
        others = cases + [x for x in base if x is not b]  # a rewrite naturally resembles its own original
        if _new(others, rewrite) and rewrite.lower() != b["question"].lower():
            cases.append({"type": "ambiguous", "question": rewrite, "expected": dict(b["expected"]),
                          "origin": {"prompt": "eval_ambiguous", "rewrite_of": b["question"],
                                     "meaning_check": same.get("reason", "")}})
    return cases


def refusals(req, n_unrelated):
    refuse = [(t["topic"], t["reason"], "out_of_scope") for t in req["must_refuse_topics"]]
    refuse += [(t["topic"], "the documents do not cover it", "ungroundable")
               for t in req["must_answer_topics"] if not t["source_docs"]]
    kinds = {topic: kind for topic, _, kind in refuse}

    def check(o):
        if not isinstance(o, dict) or not isinstance(o.get("questions"), list):
            return 'need {"questions": [...]}'
        return None
    o = ask_json("eval_refuse", check=check, temperature=TEMPERATURE, audience=req["audience"],
                 summary=req["summary"], n_unrelated=str(n_unrelated),
                 refuse_topics="\n".join(f"- {t} ({why})" for t, why, _ in refuse) or "- (none listed)")
    cases = []
    for q in o["questions"]:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not _new(cases, q["question"]):
            continue
        topic = str(q.get("topic", "unrelated"))
        cases.append({"type": kinds.get(topic, "out_of_scope"), "question": q["question"].strip(),
                      "expected": {"refuse": True, "topic": topic},
                      "origin": {"prompt": "eval_refuse"}})
    return cases


def calculator_cases(req, pool, n, dropped):
    cases = []
    candidates = [c for c in pool if len(NUM.findall(c["text"])) >= 2]
    for c in candidates[: n * 3]:
        if len(cases) >= n:
            break
        o = ask_json("eval_calc", check=lambda o: _q_ok(o) or (None if isinstance(o.get("expression"), str)
                                                               else "need an 'expression' string"),
                     temperature=TEMPERATURE, audience=req["audience"], chunk_id=c["id"], passage=c["text"])
        expr = o["expression"].replace(",", "")
        used, allowed = numbers(expr), numbers(c["text"]) | numbers(o["question"])
        result = tools.calculator(expr)
        if "error" in result or used - allowed or len(NUM.findall(expr)) < 2:
            dropped.append({"type": "calculator", "question": o["question"], "chunk": c["id"],
                            "why": f"expression {expr!r} invalid or uses numbers not in passage/question "
                                   f"({sorted(used - allowed)})"})
            continue
        value = result["result"]
        fact = str(int(value)) if float(value) == int(value) else f"{value:.2f}".rstrip("0").rstrip(".")
        # Code can verify the numbers, not the logic. Logic check = agreement: a fresh call that never sees
        # the proposed expression solves the question itself; keep the case only if both results match.
        # (A "is this correct?" verdict nitpicked valid cases live; a confused question such as
        # "5 days of vacation -> how many monthly accrual days?" yields a different derivation.)
        solve = ask_json("eval_solve_calc", check=lambda o: None if isinstance(o, dict) and isinstance(
            o.get("answerable"), bool) else 'need {"answerable": bool, "expression": str}',
            passage=c["text"], question=o["question"])
        second = tools.calculator(str(solve.get("expression") or "").replace(",", "")) if solve["answerable"] else {}
        if "result" not in second or abs(float(second["result"]) - float(value)) > 1e-6 * max(1.0, abs(value)):
            dropped.append({"type": "calculator", "question": o["question"], "chunk": c["id"],
                            "why": f"independent derivation disagrees: proposed {expr} = {fact}, "
                                   f"re-derived {solve.get('expression')!r} -> {second.get('result', 'unanswerable')}"})
            continue
        if _new(cases, o["question"]):
            cases.append({"type": "calculator", "question": o["question"].strip(),
                          "expected": {"refuse": False, "key_facts": [fact], "source_docs": [c["doc"]],
                                       "source_chunks": [c["id"]], "tool": "calculator"},
                          "origin": {"prompt": "eval_calc", "expression": expr, "unit": o.get("unit", "")}})
    return cases


def csv_cases(req, docs_dir, n):
    """No LLM: pick real rows and cells; the expected value is the cell itself."""
    supported = {d for t in req["must_answer_topics"] for d in t["source_docs"] if d.lower().endswith(".csv")}
    cases = []
    for name in sorted(supported):
        with open(Path(docs_dir) / name, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
        if len(rows) < 1:
            continue
        cols = list(rows[0].keys())
        key_col, value_cols = cols[0], [c for c in cols[1:] if c]
        for i in sorted({len(rows) // 2, len(rows) - 1, 0})[:n]:
            if len(cases) >= n or not value_cols:
                break
            row = rows[i]
            target = value_cols[(i + len(cases)) % len(value_cols)]
            if not str(row.get(target, "")).strip():
                continue
            q = f"What is the {target.replace('_', ' ')} for {key_col.replace('_', ' ')} {row[key_col]}?"
            cases.append({"type": "csv_lookup", "question": q,
                          "expected": {"refuse": False, "key_facts": [row[target].strip()], "source_docs": [name],
                                       "source_chunks": [], "tool": None},
                          "origin": {"prompt": None, "csv_row": i, "column": target}})
    return cases


def generate(req, definition, index, docs_dir):
    """Returns {"cases": [...], "dropped": [...], "counts": {...}}. Case ids are stable per type."""
    supported = {d for t in req["must_answer_topics"] for d in t["source_docs"]}
    pool = _spread([c for c in index.chunks if c["doc"] in supported and len(c["text"].split()) >= 20])
    dropped, cases = [], []

    log(f"evalgen: answerable cases from {len(pool)} passages")
    base = answerable(req, pool, TARGETS["answerable"], dropped)
    cases += base
    log("evalgen: multi-document cases")
    cases += multi_doc(req, pool, TARGETS["multi_doc"], dropped)
    log("evalgen: ambiguous rewrites")
    cases += ambiguous(base, TARGETS["ambiguous"], dropped)
    log("evalgen: refusal cases")
    cases += refusals(req, TARGETS["unrelated"])
    if "calculator" in definition["tools"]:
        log("evalgen: calculator cases")
        cases += calculator_cases(req, pool, TARGETS["calculator"], dropped)
    if "csv_lookup" in definition["tools"]:
        cases += csv_cases(req, docs_dir, TARGETS["csv_lookup"])

    if len(cases) < MIN_CASES:  # small corpus: top up with more answerable cases
        log(f"evalgen: {len(cases)} cases, topping up to {MIN_CASES}")
        extra = answerable(req, pool, TARGETS["answerable"] + (MIN_CASES - len(cases)), dropped)
        cases += [c for c in extra if _new(cases, c["question"])][: MIN_CASES - len(cases)]

    prefix = {"answerable": "A", "multi_doc": "M", "ambiguous": "B", "out_of_scope": "R", "ungroundable": "U",
              "calculator": "C", "csv_lookup": "T"}
    seen = defaultdict(int)
    for c in cases:
        seen[c["type"]] += 1
        c["id"] = f"{prefix[c['type']]}{seen[c['type']]:02d}"
    counts = dict(seen)
    if len(cases) < MIN_CASES:
        log(f"evalgen: WARNING only {len(cases)} verified cases (target {MIN_CASES}); see 'dropped'")
    return {"cases": cases, "dropped": dropped, "counts": counts, "total": len(cases)}
