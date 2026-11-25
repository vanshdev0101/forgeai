"""Requirement 6: the critic-optimizer loop.

run evals -> classify every failure (retrieval_miss / prompt_defect / hallucination / wrong_refusal)
-> apply ONE targeted fix for the largest category -> re-run. At most 3 iterations.

- One change per iteration, so every score change is attributable to exactly one change.
- retrieval_miss is fixed in code from measurements (where the expected passage ranked and scored);
  the other categories add one rule to a "Lessons from testing" section of the system prompt.
- A change is kept only if the pass count strictly rises; otherwise it is reverted and logged. (Live: a
  rule that fixed nothing was kept at 22 -> 22, then regenerated identically in the next iteration.)
- Anti-leakage: a prompt rule may not contain any eval answer or any digit; otherwise the factory could
  "fix" failures by pasting the test answers into the prompt.
"""
import copy
import re

from factory import judge
from factory.common import ask_json, log
from factory.facts import fact_in_text
from runtime.runner import Agent

MAX_ITERATIONS = 3
MIN_SCORE_FLOOR = 0.3
MAX_K = 8
CATEGORIES = {
    "retrieval_miss": "the passage with the answer never reached the assistant",
    "wrong_refusal": "the assistant had the right passage but refused anyway",
    "hallucination": "the assistant stated things its passages do not support",
    "prompt_defect": "the assistant had the passage but answered incompletely, cited wrongly, or answered "
                     "something it should have refused",
}
PRIORITY = ["retrieval_miss", "hallucination", "wrong_refusal", "prompt_defect"]  # retrieval blocks everything


def classify(r):
    """Map a judge result to one of the four categories (None if it passed)."""
    if r["passed"]:
        return None
    f = r.get("failure")
    if f == "answered_out_of_scope":
        return "prompt_defect"
    if f == "hallucination":
        return "hallucination"
    if f == "wrong_refusal":
        return "retrieval_miss" if (r.get("refusal_source") == "no_context" or not r.get("retrieval_hit")) \
            else "wrong_refusal"
    return "retrieval_miss" if not r.get("retrieval_hit") else "prompt_defect"


def _expected_position(index, case):
    """Rank (1-based) and score of the best expected passage for this question, over the whole corpus."""
    exp = case["expected"]
    hits = index.search(case["question"], k=len(index.chunks), min_score=0.0)
    for rank, h in enumerate(hits, 1):
        if h["id"] in exp.get("source_chunks", []) or (not exp.get("source_chunks") and h["doc"] in exp["source_docs"]):
            return rank, h["score"]
    return None, None


def fix_retrieval(definition, cases, failing, index):
    r = definition["retrieval"]
    positions = {c["id"]: _expected_position(index, c) for c in cases if c["id"] in failing}
    below = [s for rank, s in positions.values() if s is not None and s < r["min_score"]]
    beyond = [rank for rank, s in positions.values() if rank is not None and s >= r["min_score"] and rank > r["k"]]
    new = copy.deepcopy(definition)
    changes = []
    if below:
        target = max(MIN_SCORE_FLOOR, round(min(below) - 0.01, 3))
        if target < r["min_score"]:
            new["retrieval"]["min_score"] = target
            changes.append(f"min_score {r['min_score']} -> {target} (expected passages scored "
                           f"{sorted(round(s, 3) for s in below)}, under the threshold)")
    if beyond:
        k = min(MAX_K, max(beyond))
        if k > r["k"]:
            new["retrieval"]["k"] = k
            changes.append(f"k {r['k']} -> {k} (expected passages ranked {sorted(beyond)})")
    if not changes:
        return None, {"positions": positions, "note": "no retrieval parameter change would surface the passages"}
    return new, {"change": "; ".join(changes), "positions": positions}


def _leaks(rule, cases):
    if re.search(r"\d", rule):
        return "contains a digit"
    for c in cases:
        for f in c["expected"].get("key_facts", []):
            if len(f) > 3 and fact_in_text(f, rule):
                return f"contains the test answer {f!r}"
    return None


def fix_prompt(definition, category, failing_results, cases):
    examples = "\n".join(
        f"- Q: {r['question']}\n  Assistant answered: {r['answer'][:300]}\n  Problem: {_problem(r)}"
        for r in failing_results[:5])
    feedback, rule = "", None
    for _ in range(2):
        out = ask_json("opt_rule", check=lambda o: None if isinstance(o, dict) and isinstance(o.get("rule"), str)
                       and o["rule"].strip() else 'need {"rule": str, "why": str}',
                       system_prompt=definition["system_prompt"], category=category,
                       category_meaning=CATEGORIES[category], failures=examples + feedback)
        leak = _leaks(out["rule"], cases)
        if not leak:
            rule = out
            break
        feedback = f"\n\n(Your previous rule was rejected because it {leak}. Write a general behaviour rule.)"
    if not rule:
        return None, {"note": "rule rejected twice by the anti-leakage check"}
    if rule["rule"].strip() in definition["provenance"].get("lessons", []):
        return None, {"note": f"the model proposed a rule already in the prompt: {rule['rule'].strip()!r}"}
    new = copy.deepcopy(definition)
    lessons = new["provenance"].setdefault("lessons", [])
    lessons.append(rule["rule"].strip())
    marker = "\n\n## Lessons from testing\n"
    base = new["system_prompt"].split(marker)[0]
    new["system_prompt"] = base + marker + "\n".join(f"- {l}" for l in lessons)
    return new, {"change": f"added prompt rule: {rule['rule'].strip()!r}", "why_model": rule.get("why", "")}


def _problem(r):
    if r.get("failure") == "answered_out_of_scope":
        return "should have refused (out of scope) but answered"
    if r.get("failure") == "wrong_refusal":
        return "refused although its passages contained the answer"
    if r.get("unsupported_claims"):
        return f"unsupported claims: {r['unsupported_claims']}"
    missing = [f["fact"] for f in r.get("facts", []) if not f["stated"]]
    return f"left out required information ({len(missing)} item(s))" if missing else "cited the wrong source"


def evaluate(definition, out_dir, index, cases):
    agent = Agent(definition, base_dir=out_dir, index=index)
    results = judge.run(agent, cases)
    for r in results:
        r["category"] = classify(r)
    return results


def _summary(results, card):
    cats = {}
    for r in results:
        if r["category"]:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
    return {"passed": card["passed"], "cases": card["cases"], "pass_rate": card["pass_rate"], "categories": cats}


def loop(definition, out_dir, index, cases, selftest, write):
    """Returns (best definition, its results, history, changes, stop reason). `write(name, obj)` persists
    artifacts as they are produced."""
    results = evaluate(definition, out_dir, index, cases)
    card = judge.scorecard(results, selftest)
    history = [{"iteration": 0, "change": None, **_summary(results, card)}]
    write("results_iter0.json", results)
    write("scorecard_iter0.json", card)
    write("agent_def_iter0.json", definition)
    best, best_results = definition, results
    changes = []
    exhausted = set()  # decoding is deterministic: a reverted fix would be regenerated identically
    stop_reason = f"reached the {MAX_ITERATIONS}-iteration limit"

    for it in range(1, MAX_ITERATIONS + 1):
        failing = [r for r in best_results if r["category"]]
        if not failing:
            stop_reason = "every test case passes"
            log("optimizer: everything passes; stopping")
            break
        counts = {c: sum(r["category"] == c for r in failing) for c in PRIORITY}
        tried, candidate, info, category = set(), None, None, None
        for category in sorted(counts, key=lambda c: (-counts[c], PRIORITY.index(c))):
            if not counts[category] or category in tried or category in exhausted:
                continue
            tried.add(category)
            targets = [r for r in failing if r["category"] == category]
            if category == "retrieval_miss":
                candidate, info = fix_retrieval(best, cases, {r["id"] for r in targets}, index)
            else:
                candidate, info = fix_prompt(best, category, targets, cases)
            if candidate:
                break
            exhausted.add(category)
            changes.append({"iteration": it, "category": category, "applied": False, **info})
        if not candidate:
            stop_reason = "no applicable fix left for the remaining failures"
            log("optimizer: no applicable fix for the remaining failures; stopping")
            break

        log(f"optimizer: iteration {it}: {category}: {info['change']}")
        candidate["provenance"]["iteration"] = it
        new_results = evaluate(candidate, out_dir, index, cases)
        new_card = judge.scorecard(new_results, selftest)
        before = {r["id"]: r["passed"] for r in best_results}
        fixed = [r["id"] for r in new_results if r["passed"] and not before[r["id"]]]
        broke = [r["id"] for r in new_results if not r["passed"] and before[r["id"]]]
        kept = new_card["passed"] > sum(before.values())  # no-op changes only add prompt clutter
        entry = {"iteration": it, "category": category, "applied": True, "kept": kept, **info,
                 "targeted_cases": [r["id"] for r in failing if r["category"] == category],
                 "score_before": f"{sum(before.values())}/{len(before)}",
                 "score_after": f"{new_card['passed']}/{new_card['cases']}",
                 "newly_passing": fixed, "newly_failing": broke}
        changes.append(entry)
        write(f"results_iter{it}.json", new_results)
        write(f"scorecard_iter{it}.json", new_card)
        write(f"agent_def_iter{it}.json", candidate)
        history.append({"iteration": it, "change": info["change"], "kept": kept, **_summary(new_results, new_card)})
        if kept:
            best, best_results = candidate, new_results
        else:
            exhausted.add(category)
            log(f"optimizer: iteration {it} did not raise the score ({entry['score_before']} -> "
                f"{entry['score_after']}); reverted")
    return best, best_results, history, changes, stop_reason
