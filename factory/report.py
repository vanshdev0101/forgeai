"""Requirement 7: the honest report. Built only from the run's artifacts; leads with what still fails."""
from collections import Counter

from factory.optimizer import CATEGORIES


def _pct(x):
    return "n/a" if x is None else f"{x:.0%}"


def _problem(r):
    if r.get("failure") == "answered_out_of_scope":
        return "answered a question it must refuse"
    if r.get("failure") == "wrong_refusal":
        return "refused although the answer is in its documents" + (
            " (no passage cleared the retrieval threshold)" if r.get("refusal_source") == "no_context" else "")
    if r.get("unsupported_claims"):
        return "stated things its passages do not support: " + "; ".join(f"\"{c}\"" for c in r["unsupported_claims"][:2])
    missing = [f["fact"] for f in r.get("facts", []) if not f["stated"]]
    if missing:
        return "left out: " + ", ".join(f"\"{m}\"" for m in missing)
    return "did not cite an expected source document"


def build(req, definition, evals, history, changes, final_results, selftest, usage, stop_reason=""):
    final = history[-1]
    kept = [h for h in history if h["iteration"] == 0 or h.get("kept")]
    best = max(kept, key=lambda h: h["passed"])
    failing = [r for r in final_results if not r["passed"]]
    L = [f"# ForgeAI run report: {definition['name']}", "",
         f"> {req['brief']}", "",
         f"**Result: {best['passed']}/{best['cases']} test cases pass ({_pct(best['pass_rate'])}) after "
         f"{len(history) - 1} optimisation iteration(s).** "
         f"{len(failing)} still fail; each is listed below with the reason. The judge reproduced "
         f"{selftest['correct']}/{selftest['probes']} known verdicts in its self-test.", ""]

    L += ["## What still fails, and why", ""]
    if not failing:
        L += ["Nothing in this test set. That does not mean the agent is perfect: see the limitations "
              "section for what the test set cannot catch.", ""]
    by_cat = Counter(r["category"] for r in failing)
    for cat, n in by_cat.most_common():
        L += [f"### {cat} ({n}): {CATEGORIES[cat]}", ""]
        for r in [r for r in failing if r["category"] == cat]:
            ans = r["answer"].replace("\n", " ")
            L += [f"- **{r['id']}** ({r['type']}) *{r['question']}*  ",
                  f"  {_problem(r)}.  ",
                  f"  Answer given: \"{ans[:220]}{'...' if len(ans) > 220 else ''}\""]
        L.append("")
    if any(c.get("applied") and not c.get("kept") for c in changes) or any(not c.get("applied") for c in changes):
        L += ["Fixes the loop tried that did not help are in the change log below; they were reverted or "
              "not applied, so these failures are what the current definition actually does.", ""]

    L += ["## Scorecard per iteration", "",
          "| Iteration | Change | Kept | Passed | Pass rate | Failures by category |", "|---|---|---|---|---|---|"]
    for h in history:
        cats = ", ".join(f"{k} {v}" for k, v in sorted(h["categories"].items())) or "none"
        kept_s = "baseline" if h["iteration"] == 0 else ("yes" if h.get("kept") else "**reverted**")
        L.append(f"| {h['iteration']} | {h['change'] or 'generated agent'} | {kept_s} | {h['passed']}/{h['cases']} "
                 f"| {_pct(h['pass_rate'])} | {cats} |")
    L.append("")
    if stop_reason:
        L += [f"The loop stopped because {stop_reason}.", ""]

    L += ["## Change log", ""]
    if not changes:
        L += ["No changes: the generated agent passed everything, or no failure had an applicable fix.", ""]
    for c in changes:
        if not c.get("applied"):
            L += [f"- Iteration {c['iteration']}, **{c['category']}**: no fix applied ({c.get('note', '')}).", ""]
            continue
        L += [f"### Iteration {c['iteration']}: {c['category']}", "",
              f"- **What changed:** {c['change']}",
              f"- **Why:** {len(c['targeted_cases'])} failure(s) classified as {c['category']} "
              f"({', '.join(c['targeted_cases'])}): {CATEGORIES[c['category']]}." +
              (f" Model's rationale: {c['why_model']}" if c.get("why_model") else ""),
              f"- **Score:** {c['score_before']} -> {c['score_after']}; newly passing: "
              f"{', '.join(c['newly_passing']) or 'none'}; newly failing: {', '.join(c['newly_failing']) or 'none'}",
              f"- **Kept:** {'yes' if c['kept'] else 'no, reverted because the pass count did not rise'}", ""]

    types = Counter(r["type"] for r in final_results)
    passed = Counter(r["type"] for r in final_results if r["passed"])
    L += ["## Final results by case type", "", "| Type | Passed |", "|---|---|"]
    L += [f"| {t} | {passed[t]}/{n} |" for t, n in sorted(types.items())]
    L.append("")

    L += ["## How far to trust these numbers", "",
          f"- **Judge self-test:** {selftest['correct']}/{selftest['probes']} known verdicts reproduced "
          f"(fact verdicts {_pct(selftest.get('fact_verdict_accuracy'))}, hallucination verdicts "
          f"{_pct(selftest.get('claim_verdict_accuracy'))}). Probes: correct answer, the same padded with filler "
          "(verbosity), one number changed, one invented claim."]
    misses = [d for d in selftest["details"] if not d["judge_correct"]]
    for d in misses:
        L.append(f"  - missed: {d['probe']} on {d['case']} (facts accepted={d['facts_accepted']}, "
                 f"claims flagged={d['claims_flagged']})")
    drop = Counter(d["type"] for d in evals["dropped"])
    L += [f"- **Test set:** {evals['total']} generated cases {dict(evals['counts'])}; "
          f"{len(evals['dropped'])} candidates were dropped because their expected answer could not be verified "
          f"({dict(drop)}). Prompts: `prompts/eval_*.md`.",
          "- **Same model family:** the agent (4b), the eval generator and the judge (9b) are all qwen3.5. The "
          "judge is a different size and is never told which model answered, but shared blind spots are possible.",
          "- **Eval cases can be wrong:** facts are verified against the source text, but the question a fact is "
          "attached to is written by a model; a calculator case whose question both independent derivations "
          "misread the same way would survive.", ""]

    g = req.get("groundability", {})
    L += ["## Requirements and groundability", "", g.get("summary", ""), ""]
    for f in g.get("flags", []):
        L.append(f"- **{f['topic']}**: {f['verdict']} ({f['method']}, best passage {f['best_score']}). {f['evidence'][:200]}")
    L.append("")

    L += ["## Tools", "", "| Tool | Attached | Need signal | Evidence |", "|---|---|---|---|"]
    for t in definition["provenance"]["tool_decisions"]:
        L.append(f"| {t['tool']} | {'yes' if t['attached'] else 'no'} | {t['need_signal'] or '-'} | "
                 f"{(t['evidence'] or '-')[:90].replace('|', '/')} |")
    cal = definition["provenance"]["calibration"]
    r = definition["retrieval"]
    L += ["", "## Retrieval", "",
          f"chunk_words={r['chunk_words']}, overlap={r['overlap']}, k={r['k']}, min_score={r['min_score']}. "
          f"Calibration: off-topic probes up to {cal['off_topic_max']}, in-scope questions down to "
          f"{cal['in_scope_min']} ({cal['in_scope_source']}); gate role: {cal['gate_role']}.", ""]

    total = Counter()
    for stage in usage.values():
        total.update({k: v for k, v in stage.items() if isinstance(v, (int, float))})
    L += ["## Cost", "",
          f"{int(total['calls'])} local LLM calls, {int(total['prompt_tokens'] + total['completion_tokens'])} tokens, "
          f"{total['wall_seconds']:.0f} s wall time.", ""]
    L += ["| Stage | Calls | Tokens | Seconds |", "|---|---|---|---|"]
    for name, s in usage.items():
        L.append(f"| {name} | {int(s['calls'])} | {int(s['prompt_tokens'] + s['completion_tokens'])} | {s['wall_seconds']} |")
    L.append("")
    return "\n".join(L)
