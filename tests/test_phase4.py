"""Offline self-check for the critic-optimizer loop and the report.

    python tests/test_phase4.py
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import optimizer, report  # noqa: E402
from tests.test_phase2 import REQ  # noqa: E402

DEF = json.loads((ROOT / "examples/smoke/agent_def.json").read_text())
DEF["provenance"] = {"tool_decisions": [], "calibration": {"off_topic_max": 0.5, "in_scope_min": 0.6,
                                                           "in_scope_source": "sample_questions", "gate_role": "x"}}
CASES = [{"id": f"A0{i}", "type": "answerable", "question": f"question {i}",
          "expected": {"refuse": False, "key_facts": ["12 days", "medical certificate"],
                       "source_docs": ["leave_policy.md"], "source_chunks": [f"leave_policy.md#{i}"]}}
         for i in range(1, 4)]


def _r(cid, passed, failure=None, **kw):
    return {"id": cid, "type": "answerable", "question": f"q {cid}", "answer": "a", "passed": passed,
            "failure": failure, **kw}


def test_classification():
    c = optimizer.classify
    assert c(_r("x", True)) is None
    assert c(_r("x", False, "answered_out_of_scope")) == "prompt_defect"
    assert c(_r("x", False, "hallucination", retrieval_hit=True)) == "hallucination"
    assert c(_r("x", False, "wrong_refusal", refusal_source="no_context", retrieval_hit=True)) == "retrieval_miss"
    assert c(_r("x", False, "wrong_refusal", refusal_source="model", retrieval_hit=False)) == "retrieval_miss"
    assert c(_r("x", False, "wrong_refusal", refusal_source="model", retrieval_hit=True)) == "wrong_refusal"
    assert c(_r("x", False, "missing_facts", retrieval_hit=False)) == "retrieval_miss"
    assert c(_r("x", False, "missing_facts", retrieval_hit=True)) == "prompt_defect"


class RankIdx:
    """Expected chunk for question i sits at the given (rank, score)."""
    def __init__(self, where):
        self.where = where
        self.chunks = [{"id": f"leave_policy.md#{i}", "doc": "leave_policy.md"} for i in range(20)]

    def search(self, q, k=4, min_score=0.0):
        i = int(q.split()[-1])
        rank, score = self.where[i]
        hits = [{"id": f"other#{j}", "doc": "travel_policy.md", "score": 0.99} for j in range(rank - 1)]
        return hits + [{"id": f"leave_policy.md#{i}", "doc": "leave_policy.md", "score": score}]


def test_retrieval_fix_from_measurements():
    d = copy.deepcopy(DEF)
    d["retrieval"].update(k=4, min_score=0.6)
    new, info = optimizer.fix_retrieval(d, CASES, {"A01", "A02"}, RankIdx({1: (1, 0.55), 2: (6, 0.7), 3: (1, 0.9)}))
    assert new["retrieval"]["min_score"] == 0.54 and new["retrieval"]["k"] == 6, info
    assert d["retrieval"]["min_score"] == 0.6, "original definition must not be mutated"

    new, _ = optimizer.fix_retrieval(d, CASES, {"A01"}, RankIdx({1: (1, 0.1), 2: (1, 0.9), 3: (1, 0.9)}))
    assert new["retrieval"]["min_score"] == optimizer.MIN_SCORE_FLOOR, "never below the floor"
    new, _ = optimizer.fix_retrieval(d, CASES, {"A01"}, RankIdx({1: (30, 0.9), 2: (1, 0.9), 3: (1, 0.9)}))
    assert new["retrieval"]["k"] == optimizer.MAX_K, "k is capped"
    new, info = optimizer.fix_retrieval(d, CASES, {"A01"}, RankIdx({1: (2, 0.9), 2: (1, 0.9), 3: (1, 0.9)}))
    assert new is None and "no retrieval parameter change" in info["note"]


def test_leak_check():
    assert optimizer._leaks("Always state the exact number of days.", CASES) is None
    assert optimizer._leaks("Say employees get 12 days.", CASES) == "contains a digit"
    assert "test answer" in optimizer._leaks("Mention that a medical certificate is needed.", CASES)


def test_prompt_fix_appends_one_rule_and_retries_on_leak():
    replies = iter([{"rule": "Say 12 days of sick leave.", "why": "w"},
                    {"rule": "Answer every part of a multi-part question.", "why": "incomplete answers"}])
    seen = []

    def ask_json(_prompt, check=None, **v):
        seen.append(v["failures"])
        return next(replies)
    optimizer.ask_json = ask_json
    fails = [_r("A01", False, "missing_facts", retrieval_hit=True, facts=[{"fact": "12 days", "stated": False}])]
    new, info = optimizer.fix_prompt(copy.deepcopy(DEF), "prompt_defect", fails, CASES)
    assert "rejected because it contains a digit" in seen[1]
    assert new["system_prompt"].startswith(DEF["system_prompt"]), "base prompt must not be rewritten"
    assert new["system_prompt"].endswith("## Lessons from testing\n- Answer every part of a multi-part question.")
    assert new["provenance"]["lessons"] == ["Answer every part of a multi-part question."]

    replies = iter([{"rule": "Always say 12 days.", "why": "w"}, {"rule": "Use 12.", "why": "w"}])
    optimizer.ask_json = lambda _p, check=None, **v: next(replies)
    new, info = optimizer.fix_prompt(copy.deepcopy(DEF), "prompt_defect", fails, CASES)
    assert new is None and "anti-leakage" in info["note"]

    second = copy.deepcopy(DEF)
    second["provenance"]["lessons"] = ["Rule one."]
    second["system_prompt"] += "\n\n## Lessons from testing\n- Rule one."
    optimizer.ask_json = lambda _p, check=None, **v: {"rule": "Rule two.", "why": "w"}
    new, _ = optimizer.fix_prompt(second, "hallucination", fails, CASES)
    assert new["system_prompt"].count("## Lessons from testing") == 1 and new["system_prompt"].endswith("- Rule one.\n- Rule two.")


def _script(rounds):
    """Fake evaluate(): returns the next scripted result list; records the definitions it saw."""
    it, seen = iter(rounds), []

    def evaluate(defn, out_dir, index, cases):
        seen.append(copy.deepcopy(defn))
        res = next(it)
        for r in res:
            r["category"] = optimizer.classify(r)
        return res
    return evaluate, seen


def _run_loop(rounds, fixes):
    evaluate, seen = _script(rounds)
    optimizer.evaluate = evaluate
    fix_iter = iter(fixes)

    def fake_fix(defn, *a, **k):
        f = next(fix_iter)
        if f is None:
            return None, {"note": "nothing to do"}
        new = copy.deepcopy(defn)
        new["system_prompt"] += f
        return new, {"change": f}
    optimizer.fix_prompt = lambda defn, cat, targets, cases: fake_fix(defn)
    optimizer.fix_retrieval = lambda defn, cases, failing, index: fake_fix(defn)
    written = {}
    best, final, history, changes, stop = optimizer.loop(copy.deepcopy(DEF), ".", None, CASES,
                                                         {"correct": 1, "probes": 1},
                                                         lambda n, o: written.__setitem__(n, o))
    _run_loop.stop = stop
    return best, final, history, changes, seen, written


def _case(cid, spec):
    """spec: 'pass' | 'pd' (prompt_defect) | 'hal' (hallucination) | 'rm' (retrieval_miss)."""
    if spec == "pass":
        return _r(cid, True, retrieval_hit=True, fact_recall=1.0, agent_llm_calls=1)
    failure = {"pd": "missing_facts", "hal": "hallucination", "rm": "missing_facts"}[spec]
    return _r(cid, False, failure, retrieval_hit=spec != "rm", fact_recall=0.0, agent_llm_calls=1)


def _rounds(*specs):
    return [[_case(f"A0{i + 1}", s) for i, s in enumerate(row)] for row in specs]


def test_loop_keeps_improvements_reverts_regressions_and_logs_everything():
    rounds = _rounds(("pd", "hal", "rm"),     # 0: 0/3; retrieval_miss wins the tie on priority
                     ("pd", "hal", "pass"),   # 1: 1/3 kept
                     ("pd", "pd", "pd"),      # 2: hallucination fix -> 0/3, reverted
                     ("pass", "pass", "pass"))  # 3: prompt_defect fix on top of fix1
    best, final, history, changes, seen, written = _run_loop(rounds, [" +fix1", " +fix2", " +fix3"])
    assert [h["passed"] for h in history] == [0, 1, 0, 3]
    assert [(c["category"], c["kept"]) for c in changes] == [
        ("retrieval_miss", True), ("hallucination", False), ("prompt_defect", True)]
    assert seen[3]["system_prompt"].endswith(" +fix1 +fix3"), "fix3 must build on fix1, not on the reverted fix2"
    assert best["system_prompt"].endswith(" +fix1 +fix3")
    c1 = changes[0]
    assert c1["score_before"] == "0/3" and c1["score_after"] == "1/3"
    assert c1["newly_passing"] == ["A03"] and c1["newly_failing"] == [] and c1["targeted_cases"] == ["A03"]
    assert changes[1]["newly_failing"] == ["A03"]
    assert {"results_iter0.json", "results_iter3.json", "agent_def_iter2.json"} <= set(written)


def test_equal_score_is_not_kept():
    rounds = _rounds(("pd", "hal", "pass"), ("pd", "pass", "hal"), ("pd", "hal", "pass"))
    best, final, history, changes, seen, _ = _run_loop(rounds, [" +swap", " +noop"])
    assert changes[0]["kept"] is False and changes[1]["kept"] is False, changes
    assert best["system_prompt"] == DEF["system_prompt"], "a swap or a no-op is not progress"
    assert "in a row brought no gain" in _run_loop.stop


def test_loop_stops_when_all_pass_and_skips_exhausted_categories():
    best, final, history, changes, seen, _ = _run_loop(_rounds(("pass", "pass", "pass")), [])
    assert len(history) == 1 and changes == [] and _run_loop.stop == "every test case passes"

    # prompt_defect fix reverted -> the same category must not be retried (deterministic decoding)
    best, final, history, changes, seen, _ = _run_loop(_rounds(("pd", "pass", "pass"), ("pd", "pd", "pass")),
                                                       [" +same"])
    assert len(history) == 2 and changes[0]["kept"] is False and len(seen) == 2, "no third identical attempt"
    assert _run_loop.stop == "no applicable fix was left for the remaining failures"


def test_loop_respects_the_iteration_cap():
    rounds = _rounds(("pd", "hal", "rm"), ("pd", "hal", "pass"), ("pd", "pass", "pass"), ("pass", "pass", "pass"))
    saved = optimizer.MAX_ITERATIONS
    optimizer.MAX_ITERATIONS = 2
    try:
        best, final, history, changes, seen, _ = _run_loop(rounds, [" +a", " +b", " +c"])
    finally:
        optimizer.MAX_ITERATIONS = saved
    assert len(history) == 3 and len(seen) == 3, "must stop at the cap even though it keeps improving"
    assert _run_loop.stop == "reached the 2-iteration limit"


def test_duplicate_rule_is_not_reapplied():
    d = copy.deepcopy(DEF)
    d["provenance"]["lessons"] = ["Never state unsupported details."]
    optimizer.ask_json = lambda _p, check=None, **v: {"rule": "Never state unsupported details.", "why": "w"}
    new, info = optimizer.fix_prompt(d, "hallucination", [_r("A01", False, "hallucination")], CASES)
    assert new is None and "already in the prompt" in info["note"]


def test_budget_refuses_an_iteration_it_cannot_afford():
    from runtime import llm
    saved = dict(llm.USAGE)
    try:
        llm.USAGE.update(prompt_tokens=9000, completion_tokens=0)
        b = optimizer.Budget(max_tokens=10000, started=0)
        assert "token budget" in b.refuse_next({"tokens": 1500, "seconds": 1})
        assert b.refuse_next({"tokens": 500, "seconds": 1}) is None
        import time
        t = optimizer.Budget(max_seconds=60, started=time.time() - 50)
        assert "time budget" in t.refuse_next({"tokens": 0, "seconds": 20})
        assert optimizer.Budget().refuse_next({"tokens": 10 ** 9, "seconds": 10 ** 9}) is None, "no limit by default"
    finally:
        llm.USAGE.clear()
        llm.USAGE.update(saved)


def test_loop_stops_on_budget_before_starting_unaffordable_work():
    from runtime import llm
    saved = dict(llm.USAGE)
    evaluate, seen = _script(_rounds(("pd", "hal", "rm"), ("pd", "hal", "pass"), ("pd", "pass", "pass")))

    def costly(*a):
        llm.USAGE["prompt_tokens"] += 1000  # every evaluation pass costs 1000 tokens
        return evaluate(*a)
    optimizer.evaluate = costly
    optimizer.fix_prompt = lambda d, *a: (dict(d, system_prompt=d["system_prompt"] + " +r"), {"change": "r"})
    optimizer.fix_retrieval = optimizer.fix_prompt
    try:
        llm.USAGE.update(prompt_tokens=0, completion_tokens=0)
        out = optimizer.loop(copy.deepcopy(DEF), ".", None, CASES, {"correct": 1, "probes": 1}, lambda n, o: None,
                             optimizer.Budget(max_tokens=2500, started=0))
        history, stop = out[2], out[4]
        assert len(history) == 2, "iteration 2 would need tokens 2000 + 1000 > 2500: never started"
        assert "token budget" in stop and history[0]["cost"]["tokens"] == 1000
    finally:
        llm.USAGE.clear()
        llm.USAGE.update(saved)


def test_loop_stops_when_iterations_stop_paying():
    rounds = _rounds(("pd", "hal", "rm"), ("pd", "hal", "rm"), ("pd", "hal", "rm"), ("pass", "pass", "pass"))
    best, final, history, changes, seen, _ = _run_loop(rounds, [" +a", " +b", " +c"])
    assert len(seen) == 3 and [c["kept"] for c in changes] == [False, False], "a third attempt was not worth it"
    assert "in a row brought no gain" in _run_loop.stop


def test_a_gain_resets_the_no_gain_streak():
    rounds = _rounds(("rm", "hal", "pd"),     # 0
                     ("rm", "hal", "pd"),     # 1: retrieval fix, no gain (streak 1)
                     ("pass", "hal", "pd"),   # 2: hallucination fix, gain (streak resets to 0)
                     ("pass", "hal", "hal"),  # 3: hallucination again? exhausted -> prompt_defect, no gain (1)
                     ("pass", "pass", "pass"))  # 4: still allowed: the streak is 1, not 2
    saved = optimizer.MAX_ITERATIONS
    optimizer.MAX_ITERATIONS = 4
    try:
        best, final, history, changes, seen, _ = _run_loop(rounds, [" +a", " +b", " +c", " +d"])
    finally:
        optimizer.MAX_ITERATIONS = saved
    assert len(seen) == 5 and history[-1]["passed"] == 3, [h["passed"] for h in history]


def test_report_leads_with_remaining_failures():
    final = [_r("A01", True, retrieval_hit=True, fact_recall=1.0, category=None),
             _r("A02", False, "hallucination", unsupported_claims=["you must book premium economy"],
                category="hallucination")]
    history = [{"iteration": 0, "change": None, "passed": 1, "cases": 2, "pass_rate": 0.5,
                "categories": {"hallucination": 1}}]
    req = {**REQ, "groundability": {"summary": "2 of 3 supported.", "flags": []}}
    evals = {"total": 2, "counts": {"answerable": 2}, "dropped": []}
    st = {"correct": 11, "probes": 12, "fact_verdict_accuracy": 1.0, "claim_verdict_accuracy": 0.9,
          "details": [{"judge_correct": False, "probe": "verbose_correct", "case": "A01", "facts_accepted": True,
                       "claims_flagged": ["x"]}]}
    usage = {"x": {"calls": 3, "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0, "wall_seconds": 1.0}}
    md = report.build(req, DEF, evals, history, [], final, st, usage, "every test case passes")
    assert md.index("## What still fails") < md.index("## Scorecard per iteration")
    assert "**A02**" in md and "you must book premium economy" in md
    assert "1/2 test cases pass (50%)" in md and "11/12" in md and "missed: verbose_correct" in md
    assert "The loop stopped because every test case passes." in md
    md = report.build(req, DEF, evals, [{**history[0], "cost": {"tokens": 1200, "seconds": 90}}], [], final, st,
                      usage, "the token budget would be exceeded", {"max_tokens": 50000, "max_seconds": None,
                                                                    "spent": {"tokens": 1200, "seconds": 95}})
    assert "## Budget" in md and "Limit: 50000 tokens" in md and "| 0 | 1200 | 1.5 |" in md, md[md.find("## Budget"):][:400]


if __name__ == "__main__":
    saved = (optimizer.evaluate, optimizer.fix_prompt, optimizer.fix_retrieval, optimizer.ask_json)
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        optimizer.evaluate, optimizer.fix_prompt, optimizer.fix_retrieval, optimizer.ask_json = saved
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
