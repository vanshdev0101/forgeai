"""Mutation check for the Phase 3 suite (eval generator + judge).

    python tests/mutate_phase3.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.mutation import run_suite  # noqa: E402

E, J, F = "factory/evalgen.py", "factory/judge.py", "factory/facts.py"
MUTANTS = [
    # eval generator
    ("facts not checked against passage", E, "if (f not in out and fact_in_text(f, passage)", "if (f not in out and True"),
    ("relevance check removed", E, "and (reference is None or fact_in_text(f, reference))\n", "\n"),
    ("question premises kept as facts", E, "and not (question and fact_in_text(f, question))):", "):"),
    ("negative calc results kept", E, "        if value <= 0:", "        if False:"),
    ("long facts kept whole", E, "if len(fact.split()) <= MAX_FACT_WORDS:", "if True:"),
    ("code digits count as numbers", E, r"(?<![A-Za-z\d])\d[\d,]*", r"\d[\d,]*"),
    ("unit may be a function word", E, r"(?!(?:for|and|of|to|in|on|or|the|a|an|with|per|by|from|may|is|are)\b)", ""),
    ("calc numbers not checked", E, "if \"error\" in result or used - allowed or", "if \"error\" in result or"),
    ("calc agreement skipped", E,
     "if \"result\" not in second or abs(float(second[\"result\"]) - float(value)) > 1e-6 * max(1.0, abs(value)):",
     "if False:"),
    ("solver sees the proposal", E, "passage=c[\"text\"], question=o[\"question\"])",
     "passage=c[\"text\"], question=o[\"question\"] + \" \" + expr)"),
    ("rewrite meaning check ignored", E, "if not same[\"same_information\"]:", "if False:"),
    ("near-duplicates allowed", E, "return bool(question.strip()) and not any(_similar(question, c[\"question\"]) for c in cases)",
     "return bool(question.strip())"),
    ("multi needs only one side", E, "if not (fa and fb):", "if not (fa or fb):"),
    ("refusal cases not typed", E, "cases.append({\"type\": kinds.get(topic, \"out_of_scope\")",
     "cases.append({\"type\": \"out_of_scope\""),
    # judge
    ("refusal not required", J, "r.update(passed=refused, checks={\"refusal\": refused})",
     "r.update(passed=True, checks={\"refusal\": True})"),
    ("wrong refusal not failed", J, "    if refused:\n        r.update(passed=False, failure=\"wrong_refusal\"",
     "    if False:\n        r.update(passed=False, failure=\"wrong_refusal\""),
    ("llm yes trusted blindly", J, "if o[\"states_fact\"] and span_supports(span, fact, answer):", "if o[\"states_fact\"]:"),
    ("claims not verified as quotes", J, "if norm(c) and norm(c) in norm(answer) and is_checkable_claim(c, context)]",
     "if norm(c)]"),
    ("claims filter skipped", J, "and norm(c) in norm(answer) and is_checkable_claim(c, context)]",
     "and norm(c) in norm(answer)]"),
    ("grounding ignored", J, "checks = {\"refusal\": True, \"facts\": recall == 1.0, \"grounded\": grounded,",
     "checks = {\"refusal\": True, \"facts\": recall == 1.0, \"grounded\": True,"),
    ("claims ignored in verdict", J, "\"no_unsupported_claims\": not claims}", "\"no_unsupported_claims\": True}"),
    ("question hidden from claims judge", J, "question=question or \"(none)\",", "question=\"(none)\","),
    ("selftest ignores claim verdict", J, "\"judge_correct\": fact_right and claim_right,", "\"judge_correct\": fact_right,"),
    ("paraphrased refusal ignored", J, "    return trace[\"refused\"] or (bool(_REFUSAL.search", "    return trace[\"refused\"] or (False and bool(_REFUSAL.search"),
    ("refusal with figures accepted", J, "and not re.search(r\"\\d\", trace[\"answer\"]))", ")"),
    # facts
    ("numbers not required", F, "    if fnums - numbers(text):\n        return False", "    if False:\n        return False"),
    ("span numbers not required", F, "return not (numbers(fact) - numbers(span))", "return True"),
    ("number words not normalised", F, "        w = _WORDNUM.get(raw, raw)", "        w = raw"),
    ("compound number words split", F, "        if tens_word and raw in _WORDNUM and len(w) == 1 and w != \"0\":",
     "        if False:"),
    ("written digits merged", F, "        if tens_word and raw in _WORDNUM and len(w) == 1 and w != \"0\":",
     "        if out and out[-1] in _TENS and len(w) == 1 and w != \"0\":"),
    ("ordinals not normalised", F, "t = re.sub(r\"\\b(\\d+)(st|nd|rd|th)\\b\", r\"\\1\", t)  # 31st -> 31", "pass"),
    ("underscores kept", F, "t = str(text).lower().replace(\"_\", \" \")", "t = str(text).lower()"),
    ("no stemming", F, "    for suf in (\"ing\", \"ed\", \"s\"):", "    for suf in ():"),
    ("digits merged across spaces", F, "t = re.sub(r\"(?<=\\d)[,\u00a0](?=\\d{2,3}\\b)\", \"\", t)",
     "t = re.sub(r\"(?<=\\d)[,\u00a0 ](?=\\d{2,3}\\b)\", \"\", t)"),
    ("filler counted as claim", F, "    if not nums and len(in_ctx) < 2:\n        return False",
     "    if False:\n        return False"),
    ("restatement counted as claim", F,
     "    if not (nums - numbers(context)) and len(in_ctx) == len(words):  # incl. a bare supported \"$350.53\"\n        return False",
     "    if False:\n        return False"),
]

if __name__ == "__main__":
    sys.exit(1 if run_suite("tests/test_phase3.py", MUTANTS) else 0)
