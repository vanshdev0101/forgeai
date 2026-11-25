"""Mutation check for the Phase 4 suite (critic-optimizer loop + report).

    python tests/mutate_phase4.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.mutation import run_suite  # noqa: E402

O, R = "factory/optimizer.py", "factory/report.py"
MUTANTS = [
    ("out-of-scope answer not a prompt defect", O, "if f == \"answered_out_of_scope\":\n        return \"prompt_defect\"",
     "if f == \"answered_out_of_scope\":\n        return \"hallucination\""),
    ("gate refusal not a retrieval miss", O, "r.get(\"refusal_source\") == \"no_context\" or not r.get(\"retrieval_hit\")",
     "not r.get(\"retrieval_hit\")"),
    ("missing facts always prompt defect", O, "return \"retrieval_miss\" if not r.get(\"retrieval_hit\") else \"prompt_defect\"",
     "return \"prompt_defect\""),
    ("min_score floor removed", O, "target = max(MIN_SCORE_FLOOR, round(min(below) - 0.01, 3))",
     "target = round(min(below) - 0.01, 3)"),
    ("k cap removed", O, "k = min(MAX_K, max(beyond))", "k = max(beyond)"),
    ("definition mutated in place", O, "    new = copy.deepcopy(definition)\n    changes = []",
     "    new = definition\n    changes = []"),
    ("digits allowed in rules", O, "    if re.search(r\"\\d\", rule):\n        return \"contains a digit\"",
     "    if False:\n        return \"contains a digit\""),
    ("test answers allowed in rules", O, "if len(f) > 3 and fact_in_text(f, rule):", "if False:"),
    ("no retry after a leak", O, "    for _ in range(2):\n        out = ask_json(\"opt_rule\"",
     "    for _ in range(1):\n        out = ask_json(\"opt_rule\""),
    ("prompt rewritten instead of appended", O, "base = new[\"system_prompt\"].split(marker)[0]",
     "base = \"\""),
    ("regressions kept", O, "kept = new_card[\"passed\"] > sum(before.values())", "kept = True"),
    ("equal score kept", O, "kept = new_card[\"passed\"] > sum(before.values())", "kept = new_card[\"passed\"] >= sum(before.values())"),
    ("duplicate rule reapplied", O, "if rule[\"rule\"].strip() in definition[\"provenance\"].get(\"lessons\", []):", "if False:"),
    ("reverted category retried", O, "if not counts[category] or category in tried or category in exhausted:",
     "if not counts[category] or category in tried:"),
    ("iteration cap ignored", O, "for it in range(1, MAX_ITERATIONS + 1):", "for it in range(1, MAX_ITERATIONS + 3):"),
    ("does not stop when all pass", O, "        if not failing:\n            stop_reason = \"every test case passes\"",
     "        if False:\n            stop_reason = \"every test case passes\""),
    ("report hides failures", R, "    failing = [r for r in final_results if not r[\"passed\"]]",
     "    failing = []"),
]

if __name__ == "__main__":
    sys.exit(1 if run_suite("tests/test_phase4.py", MUTANTS) else 0)
