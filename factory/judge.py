"""Requirement 5: the judge.

Per case, run the agent through the generic runner and score it. Deterministic checks first; the LLM
judge (factory model, 9b, a different model from the 4b agent) is used only where code cannot decide,
and its verdicts are themselves checked:

  refusal      should it refuse? did it?                                       code
  facts        each expected key fact stated?                                  code, then per-fact LLM
                 an LLM "yes" only counts if its quoted span is really in the answer and carries every
                 number of the fact (a judge that accepts a changed number is overruled)
  grounded     cites a passage from an expected source document (or used the expected tool)   code
  claims       sentences the retrieved passages and tool results don't support   LLM, quotes verified
  tool         expected tool used                                              code (recorded, not gating)

Bias defences: per-fact binary questions (no 1-10 quality score, so length can't buy points: verbosity
bias); no pairwise comparisons (position bias); judge model != agent model and the judge is never told
which model wrote the answer (self-preference). judge_selftest() measures the judge on answers whose
correct verdict is known, every run, and reports it next to the scores.
"""
import re
import time

from factory.common import ask_json, log
from factory.facts import fact_in_text, is_checkable_claim, norm, span_supports
from runtime import llm


def _fact_check(question, fact, answer, source=""):
    if fact_in_text(fact, answer):
        return {"fact": fact, "stated": True, "method": "deterministic"}

    def check(o):
        if not isinstance(o, dict) or not isinstance(o.get("states_fact"), bool):
            return 'need {"states_fact": bool, "answer_span": str}'
        return None
    o = ask_json("judge_fact", check=check, question=question, fact=fact, answer=answer,
                 source=_source_sentence(fact, source))
    span = str(o.get("answer_span") or "")
    if o["states_fact"] and span_supports(span, fact, answer):
        return {"fact": fact, "stated": True, "method": "llm", "span": span}
    method = "llm_overruled" if o["states_fact"] else "llm"
    return {"fact": fact, "stated": False, "method": method, "span": span or None}


def _source_sentence(fact, passage):
    """The sentence of the source passage that contains the fact, to show the judge its meaning."""
    for s in re.split(r"(?<=[.;\n])\s+", passage or ""):
        if fact_in_text(fact, s):
            return s.strip()
    return fact


def _claims_check(answer, passages, tool_results, question=""):
    def check(o):
        if not isinstance(o, dict) or not isinstance(o.get("unsupported_claims"), list):
            return 'need {"unsupported_claims": [...]}'
        return None
    o = ask_json("judge_claims", check=check, passages=passages or "(none)", question=question or "(none)",
                 tool_results=tool_results or "(none)", answer=answer)
    claims = [str(c).strip() for c in o["unsupported_claims"] if str(c).strip()]
    context = " ".join([passages, tool_results, question])
    # Keep a claim only if the judge really quoted it from the answer and it is a checkable claim
    # (not courtesy filler, not a verbatim restatement of the passages). See facts.is_checkable_claim.
    verified = [c for c in claims if norm(c) and norm(c) in norm(answer) and is_checkable_claim(c, context)]
    return verified, [c for c in claims if c not in verified]


_REFUSAL = re.compile(r"\b(cannot|can't|can not|unable to|not able to|do not have|don't have|no information|"
                      r"not (included|covered|available|specified|mentioned|provided) in|outside (my|the) scope|"
                      r"please contact)\b", re.I)


def reads_as_refusal(trace):
    """A refusal in other words: refusal phrasing and no figures. Live: "I am unable to provide information on
    customs duties ... not included in the provided documents" had refused=false and was scored as answering."""
    return trace["refused"] or (bool(_REFUSAL.search(trace["answer"])) and not re.search(r"\d", trace["answer"]))


def score(case, trace, index):
    exp = case["expected"]
    retrieved = [h["id"] for h in trace["retrieved"]]
    tools_used = [t["name"] for t in trace["tool_calls"]]
    r = {"id": case["id"], "type": case["type"], "question": case["question"], "answer": trace["answer"],
         "refused": trace["refused"], "refusal_source": trace.get("refusal_source"),
         "citations": trace["citations"], "retrieved": trace["retrieved"], "tools_used": tools_used,
         "violations": trace["violations"]}

    refused = reads_as_refusal(trace)
    r["refused_paraphrased"] = refused and not trace["refused"]
    if exp["refuse"]:
        r.update(passed=refused, checks={"refusal": refused})
        if not refused:
            r["failure"] = "answered_out_of_scope"
        return r

    r["retrieval_hit"] = (any(c in retrieved for c in exp["source_chunks"]) if exp["source_chunks"]
                          else any(i.split("#")[0] in exp["source_docs"] for i in retrieved))
    if refused:
        r.update(passed=False, failure="wrong_refusal", checks={"refusal": False}, fact_recall=0.0)
        return r

    source = " ".join(index.get(i)["text"] for i in exp["source_chunks"] if index.get(i))
    facts = [_fact_check(case["question"], f, trace["answer"], source) for f in exp["key_facts"]]
    recall = sum(f["stated"] for f in facts) / len(facts) if facts else 1.0
    cited_docs = {c.split("#")[0] for c in trace["citations"]}
    tool_ok = exp.get("tool") in tools_used if exp.get("tool") else None
    grounded = bool(cited_docs & set(exp["source_docs"])) or bool(tool_ok)
    passages = "\n\n".join(f"[{i}] {index.get(i)['text']}" for i in retrieved if index.get(i))
    tool_results = "\n".join(f"{t['name']}({t['args']}) -> {t['result']}" for t in trace["tool_calls"])
    claims, rejected_claims = _claims_check(trace["answer"], passages, tool_results, case["question"])

    checks = {"refusal": True, "facts": recall == 1.0, "grounded": grounded, "no_unsupported_claims": not claims}
    passed = all(checks.values())
    r.update(passed=passed, checks=checks, fact_recall=round(recall, 3), facts=facts,
             unsupported_claims=claims, judge_claims_rejected=rejected_claims, tool_used_as_expected=tool_ok)
    if not passed:
        r["failure"] = ("hallucination" if claims else "missing_facts" if recall < 1.0 else "ungrounded")
    return r


def run(agent, cases):
    results = []
    for c in cases:
        calls0, t0 = llm.USAGE["calls"], time.time()
        trace = agent.answer(c["question"])
        agent_calls, agent_s = llm.USAGE["calls"] - calls0, time.time() - t0
        res = score(c, trace, agent.index)
        res.update(agent_llm_calls=agent_calls, agent_seconds=round(agent_s, 1))
        results.append(res)
        log(f"judge: {c['id']} {'PASS' if res['passed'] else 'FAIL ' + res.get('failure', '')}")
    return results


def scorecard(results, selftest=None):
    def rate(xs):
        return round(sum(xs) / len(xs), 3) if xs else None
    answer = [r for r in results if "fact_recall" in r]
    refuse = [r for r in results if r["type"] in ("out_of_scope", "ungroundable")]
    by_type = {}
    for r in results:
        b = by_type.setdefault(r["type"], {"n": 0, "passed": 0})
        b["n"] += 1
        b["passed"] += r["passed"]
    failures = {}
    for r in results:
        if not r["passed"]:
            failures[r["failure"]] = failures.get(r["failure"], 0) + 1
    return {
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "pass_rate": rate([r["passed"] for r in results]),
        "by_type": by_type, "failures": failures,
        "answerable_fact_recall": rate([r["fact_recall"] for r in answer]),
        "refusal_accuracy": rate([r["passed"] for r in refuse]),
        "wrong_refusal_rate": rate([r.get("failure") == "wrong_refusal" for r in answer]),
        "hallucination_rate": rate([bool(r.get("unsupported_claims")) for r in answer]),
        "retrieval_hit_rate": rate([r["retrieval_hit"] for r in answer]),
        "mean_agent_llm_calls": rate([r["agent_llm_calls"] for r in results]),
        "judge_selftest": selftest,
    }


def _bump_numbers(text):
    return re.sub(r"\d+(?:\.\d+)?", lambda m: str(int(float(m.group(0))) + 7), text)


def judge_selftest(cases, index, n=3):
    """Grade answers whose correct verdict is known. Reported every run so a broken judge shows."""
    probes = []
    for c in [c for c in cases if c["type"] == "answerable"][:n]:
        facts, q = c["expected"]["key_facts"], c["question"]
        correct = "According to the policy, " + "; ".join(facts) + "."
        filler = (" Please note this is general guidance, and you should always feel free to reach out to the "
                  "relevant team if anything is unclear; they are always happy to help you with any questions.")
        # (probe, answer, facts should be accepted, an unsupported claim should be flagged)
        probes.append((c, "correct", correct, True, False))
        probes.append((c, "verbose_correct", correct + filler * 3, True, False))  # length must not matter
        if any(ch.isdigit() for f in facts for ch in f):
            probes.append((c, "number_changed", _bump_numbers(correct), False, True))
        probes.append((c, "fabricated_claim", correct + " Employees also receive 45 days of paid bonus leave "
                                                        "every year for the Founder's Day celebration.", True, True))
    results = []
    for c, kind, answer, facts_expected, claim_expected in probes:
        passages = "\n\n".join(index.get(i)["text"] for i in c["expected"]["source_chunks"] if index.get(i))
        facts_ok = all(_fact_check(c["question"], f, answer, passages)["stated"] for f in c["expected"]["key_facts"])
        claims, _ = _claims_check(answer, passages, "", c["question"])
        fact_right, claim_right = facts_ok == facts_expected, bool(claims) == claim_expected
        results.append({"case": c["id"], "probe": kind, "judge_correct": fact_right and claim_right,
                        "fact_verdict_correct": fact_right, "claim_verdict_correct": claim_right,
                        "facts_accepted": facts_ok, "claims_flagged": claims})
    log(f"judge self-test: {sum(r['judge_correct'] for r in results)}/{len(results)} known verdicts reproduced")
    def acc(key):
        return round(sum(r[key] for r in results) / len(results), 3) if results else None
    return {"probes": len(results), "correct": sum(r["judge_correct"] for r in results),
            "accuracy": acc("judge_correct"), "fact_verdict_accuracy": acc("fact_verdict_correct"),
            "claim_verdict_accuracy": acc("claim_verdict_correct"), "details": results}
