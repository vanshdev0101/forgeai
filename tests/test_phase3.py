"""Offline self-check for the eval generator and judge (factory model stubbed per prompt).

    python tests/test_phase3.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import common, evalgen, facts, judge  # noqa: E402
from tests.test_phase1 import SMOKE  # noqa: E402
from tests.test_phase2 import REQ  # noqa: E402

LEAVE = ("Employees receive 12 days of paid sick leave per calendar year. A medical certificate is required "
         "for any absence longer than 2 consecutive working days.")
TRAVEL = "Shore staff receive a daily allowance of INR 2,500 for domestic travel and USD 90 for international travel."


def stub(responses):
    calls = []

    def ask_json(_prompt, check=None, temperature=0.0, **values):
        calls.append((_prompt, values))
        r = responses[_prompt]
        out = r(values) if callable(r) else r
        err = check(out) if check else None
        if err:
            raise ValueError(f"stub output for {_prompt} failed check: {err}")
        return out
    for mod in (common, evalgen, judge):
        mod.ask_json = ask_json
    return calls


class Idx:
    def __init__(self, chunks):
        self.chunks = chunks

    def get(self, cid):
        return next((c for c in self.chunks if c["id"] == cid), None)


CHUNKS = [{"id": "leave_policy.md#0", "doc": "leave_policy.md", "text": LEAVE},
          {"id": "travel_policy.md#0", "doc": "travel_policy.md", "text": TRAVEL}]


def test_fact_matching():
    assert facts.fact_in_text("INR 2,500", "You get INR 2500 a day.")
    assert facts.fact_in_text("2,27,500", "Total: INR 227500")
    assert facts.fact_in_text("2.0 days", "accrues 2 days monthly")
    assert not facts.fact_in_text("12 days", "You get 13 days of sick leave."), "numbers must match exactly"
    assert not facts.fact_in_text("2 consecutive working days", "more than 3 consecutive working days")
    assert facts.fact_in_text("medical certificate is required", "A Medical Certificate is required.")
    assert not facts.numbers("grade 3 24 days") == {"324"}, "space-separated digits must not merge"
    assert facts.span_supports("12 days of paid sick leave", "12 days", "You get 12 days of paid sick leave.")
    assert not facts.span_supports("13 days", "12 days", "You get 13 days."), "changed number must be overruled"
    assert not facts.span_supports("invented span", "12 days", "You get 12 days."), "span must be in the answer"


def test_normaliser_fixes_found_live():
    assert facts.fact_in_text("2 consecutive working days", "more than two consecutive working days")  # A08
    assert facts.fact_in_text("lapses on 31 December", "Any unused leave will lapse by December 31st.")  # A02
    assert facts.fact_in_text("annual_leave_days: 21", "you get 21 days of annual leave")  # CSV column names
    assert facts.fact_in_text("31st December", "it lapses on 31 December"), "ordinal inside the fact"
    assert facts.fact_in_text("26 weeks", "eligible for twenty-six weeks of paid maternity leave")
    assert facts.numbers("twenty-six weeks") == {"26"} and facts.numbers("20 6") == {"20", "6"}, \
        "compound number words combine; written digits never do"
    assert facts.fact_in_text("auto-create a test set from the documents themselves",
                              "you must auto-generate test sets (at least 20 cases) from the documents themselves"), \
        "M02: plural 'sets' must stem to 'set'"
    assert not facts.fact_in_text("annual_leave_days: 21", "you get 18 days of annual leave")


def test_claim_filter():
    ctx = "Flights of 6 hours or longer may be booked in premium economy with Head of Department approval."
    filler = "Please note this is general guidance; feel free to reach out to the relevant team with questions."
    assert not facts.is_checkable_claim(filler, ctx), "courtesy filler is not a claim (self-test, verbose probe)"
    assert not facts.is_checkable_claim("According to the policy, flights of 6 hours may be booked in premium "
                                        "economy.", ctx), "verbatim restatement is not unsupported"
    assert facts.is_checkable_claim("you must book flights in premium economy due to the duration", ctx), "M03"
    assert facts.is_checkable_claim("you get an additional 4 days of carry-over", ctx), "M01: unsupported number"
    assert not facts.is_checkable_claim("$350.53", "unit_price_usd: 350.53"), "a bare supported number is no claim"
    assert facts.is_checkable_claim("$999.99", "unit_price_usd: 350.53")


def test_facts_must_be_short_and_in_the_reference_answer():
    assert evalgen._verified(["12 days", "Employees receive 12 days of paid sick leave per calendar year."],
                             LEAVE, "You get 12 days, as employees receive 12 days of paid sick leave per "
                                    "calendar year.") == ["12 days"], "long sentence-facts shrink to their numbers"
    assert evalgen._shorten("Shore staff travelling for work receive a daily allowance of INR 2,500 for "
                            "domestic travel and USD 90 for international travel.") == ["INR 2,500", "USD 90"]
    assert evalgen._shorten("Unused annual leave of up to 10 days may be carried into the next calendar year") \
        == ["10 days"]
    assert evalgen._shorten("Grade G5 staff in the Director band are entitled to the most annual leave days") == [], \
        "no number: dropped; and G5 is a code, not a number"
    assert evalgen._verified(["INR 2,500", "within"], TRAVEL, "Economy is mandatory.") == [], \
        "facts the reference answer doesn't mention are irrelevant to the question (A06)"


def test_facts_restating_the_question_are_not_required():
    assert evalgen._verified(["under 6 hours", "economy class"], "Economy class for flights under 6 hours.",
                             "Economy class, since it is under 6 hours.",
                             "What class must I book for a journey under six hours?") == ["economy class"]


def test_non_positive_calculator_results_are_dropped():
    stub({"eval_calc": {"question": "I spent INR 3,000 of my INR 2,500 allowance. How much is left?",
                        "expression": "2500 - 3000", "unit": "INR"},
          "eval_solve_calc": {"answerable": True, "expression": "2500 - 3000"}})
    dropped = []
    assert evalgen.calculator_cases(REQ, CHUNKS, 1, dropped) == [] and "non-positive" in dropped[-1]["why"]


def test_answerable_drops_unverified_facts():
    replies = iter([
        {"question": "How many sick days do I get?", "answer": "You get 12 days.", "key_facts": ["12 days", "15 bonus days"]},
        {"question": "What is the domestic allowance?", "answer": "x", "key_facts": ["INR 9,999"]},  # fabricated
        {"question": "When is a certificate needed?", "answer": "For absences longer than 2 consecutive working days.", "key_facts": ["longer than 2 consecutive working days"]},
    ])
    stub({"eval_answerable": lambda v: next(replies)})
    dropped = []
    cases = evalgen.answerable(REQ, CHUNKS, 2, dropped)
    assert [c["expected"]["key_facts"] for c in cases] == [["12 days"], ["longer than 2 consecutive working days"]]
    assert len(dropped) == 1 and "INR 9,999" in dropped[0]["why"]
    assert cases[0]["expected"]["source_chunks"] == ["leave_policy.md#0"]


def test_small_corpus_reuses_passages_with_an_avoid_list():
    seen_avoid = []

    def reply(v):
        seen_avoid.append(v["avoid"])
        topics = ["sick leave entitlement", "certificate rules", "carry over limits"]
        return {"question": f"Question number {len(seen_avoid)}: what about {topics[len(seen_avoid) - 1]}?",
                "answer": "12 days", "key_facts": ["12 days"]}
    stub({"eval_answerable": reply})
    cases = evalgen.answerable(REQ, CHUNKS[:1], 3, [])
    assert len(cases) == 3 and seen_avoid[0] == "" and "Question number 1" in seen_avoid[1]


def test_multi_doc_needs_a_fact_from_each_passage():
    stub({"eval_multi": {"question": "Sick abroad: allowance and certificate?", "answer": "12 days sick; USD 90 a day.",
                         "facts_a": ["12 days"], "facts_b": ["USD 90"]}})
    cases = evalgen.multi_doc(REQ, CHUNKS, 1, [])
    assert cases and cases[0]["expected"]["source_docs"] == ["leave_policy.md", "travel_policy.md"]
    dropped = []
    stub({"eval_multi": {"question": "Sick abroad: allowance and certificate?", "answer": "12 days; EUR 70 a day.",
                         "facts_a": ["12 days"], "facts_b": ["EUR 70"]}})  # A verifies, B is not in passage B
    assert evalgen.multi_doc(REQ, CHUNKS, 1, dropped) == [] and dropped


def test_calculator_expected_value_is_computed_and_numbers_checked():
    stub({"eval_calc": {"question": "Our 7 staff travel domestically for 13 days. Total allowance?",
                        "expression": "7 * 13 * 2500", "unit": "INR"},
          "eval_solve_calc": {"answerable": True, "expression": "13 * 7 * 2500"}})
    cases = evalgen.calculator_cases(REQ, CHUNKS, 1, [])
    assert cases[0]["expected"]["key_facts"] == ["227500"] and cases[0]["expected"]["tool"] == "calculator"

    dropped = []
    stub({"eval_calc": {"question": "Our staff travel for 13 days. Total?", "expression": "7 * 13 * 3100", "unit": ""}})
    assert evalgen.calculator_cases(REQ, CHUNKS, 1, dropped) == [] and "3100" in dropped[0]["why"]


def test_csv_cases_come_from_real_cells():
    req = json.loads(json.dumps(REQ))
    cases = evalgen.csv_cases(req, SMOKE / "docs", 2)
    import csv
    rows = list(csv.DictReader(open(SMOKE / "docs" / "leave_entitlements.csv")))
    for c in cases:
        row = rows[c["origin"]["csv_row"]]
        assert c["expected"]["key_facts"] == [row[c["origin"]["column"]]] and row["grade"] in c["question"]


def test_near_duplicates_are_rejected():
    cases = [{"question": "After a domestic trip, how many unused annual leave days can an employee carry over?"}]
    assert not evalgen._new(cases, "After a domestic trip, how many unused annual leave days can I carry over?")
    assert evalgen._new(cases, "What is the international daily allowance?")


def test_ambiguous_rewrites_are_meaning_checked():
    base = [{"type": "answerable", "question": "What is the daily allowance for domestic work travel?",
             "expected": {"refuse": False, "key_facts": ["INR 2,500"]}},
            {"type": "answerable", "question": "How many sick days do I get each year?",
             "expected": {"refuse": False, "key_facts": ["12 days"]}}]
    rewrites = iter([{"question": "how much do we get paid daily if working at home?"},
                     {"question": "sick days per yr??"}])
    verdicts = iter([{"same_information": False, "reason": "travel became working from home"},
                     {"same_information": True, "reason": "same"}])
    stub({"eval_ambiguous": lambda v: next(rewrites), "eval_check_rewrite": lambda v: next(verdicts)})
    dropped = []
    cases = evalgen.ambiguous(base, 2, dropped)
    assert [c["question"] for c in cases] == ["sick days per yr??"] and cases[0]["expected"]["key_facts"] == ["12 days"]
    assert "working from home" in dropped[0]["why"]


def test_calculator_logic_needs_an_agreeing_independent_derivation():
    calls = stub({"eval_calc": {"question": "If 4 of us travel domestically, how much allowance per day in total?",
                                "expression": "4 * 90", "unit": "INR"},
                  "eval_solve_calc": {"answerable": True, "expression": "4 * 2500"}})
    dropped = []
    assert evalgen.calculator_cases(REQ, CHUNKS, 1, dropped) == []
    assert any("disagrees" in d["why"] and "10000" in d["why"] for d in dropped), dropped
    solve_inputs = [v for n, v in calls if n == "eval_solve_calc"]
    assert solve_inputs and all("4 * 90" not in str(v) for v in solve_inputs), "solver must not see the proposal"

    stub({"eval_calc": {"question": "If 4 of us travel domestically, how much allowance per day in total?",
                        "expression": "4 * 2500", "unit": "INR"},
          "eval_solve_calc": {"answerable": False, "expression": ""}})
    dropped = []
    assert evalgen.calculator_cases(REQ, CHUNKS, 1, dropped) == [] and "unanswerable" in dropped[-1]["why"]


def test_refusals_typed_by_topic():
    req = json.loads(json.dumps(REQ))
    stub({"eval_refuse": {"questions": [
        {"question": "What is Priya's salary?", "topic": "Individual salaries"},
        {"question": "How long is maternity leave?", "topic": "Maternity leave"},
        {"question": "Can you book me a cab?", "topic": "unrelated"}]}})
    cases = evalgen.refusals(req, 1)
    assert [c["type"] for c in cases] == ["out_of_scope", "ungroundable", "out_of_scope"]
    assert all(c["expected"]["refuse"] for c in cases)


def _trace(answer, refused=False, citations=(), retrieved=("leave_policy.md#0",), tools=()):
    return {"answer": answer, "refused": refused, "refusal_source": "model" if refused else None,
            "citations": list(citations), "retrieved": [{"id": i, "score": 0.8} for i in retrieved],
            "tool_calls": [{"name": t, "args": {}, "result": {"result": 1}} for t in tools], "violations": []}


CASE = {"id": "A01", "type": "answerable", "question": "How many sick days?",
        "expected": {"refuse": False, "key_facts": ["12 days"], "source_docs": ["leave_policy.md"],
                     "source_chunks": ["leave_policy.md#0"]}}


def test_judge_deterministic_paths_skip_the_llm():
    calls = stub({"judge_claims": {"unsupported_claims": []},
                  "judge_fact": lambda v: (_ for _ in ()).throw(AssertionError("fact found by code"))})
    r = judge.score(CASE, _trace("You get 12 days.", citations=["leave_policy.md#0"]), Idx(CHUNKS))
    assert r["passed"] and r["facts"][0]["method"] == "deterministic"
    assert [n for n, _ in calls] == ["judge_claims"]

    refuse_case = {"id": "R01", "type": "out_of_scope", "question": "salary?", "expected": {"refuse": True}}
    calls = stub({})
    assert judge.score(refuse_case, _trace("x", refused=True), Idx(CHUNKS))["passed"] and calls == []
    r = judge.score(refuse_case, _trace("It is 9 LPA."), Idx(CHUNKS))
    assert not r["passed"] and r["failure"] == "answered_out_of_scope"

    r = judge.score(CASE, _trace("Sorry.", refused=True), Idx(CHUNKS))
    assert r["failure"] == "wrong_refusal" and r["retrieval_hit"] is True


def test_paraphrased_refusals_count_as_refusals():
    refuse_case = {"id": "U01", "type": "ungroundable", "question": "customs duties?", "expected": {"refuse": True}}
    stub({})
    t = _trace("I am unable to provide information on customs duties; it is not included in the provided documents.")
    r = judge.score(refuse_case, t, Idx(CHUNKS))
    assert r["passed"] and r["refused_paraphrased"], r
    r = judge.score(CASE, t, Idx(CHUNKS))
    assert r["failure"] == "wrong_refusal", "a paraphrased refusal of an answerable question is a wrong refusal"
    stub({"judge_claims": {"unsupported_claims": []}})
    t = _trace("I cannot be sure, but it is 9 LPA.")
    assert not judge.score(refuse_case, t, Idx(CHUNKS))["passed"], "refusal words plus a figure is an answer"


def test_judge_llm_yes_is_verified():
    stub({"judge_claims": {"unsupported_claims": []},
          "judge_fact": {"states_fact": True, "answer_span": "a dozen days"}})
    r = judge.score(CASE, _trace("You get a dozen days.", citations=["leave_policy.md#0"]), Idx(CHUNKS))
    assert not r["passed"] and r["facts"][0]["method"] == "llm_overruled", "span lacks the number 12"

    cert = {**CASE, "expected": {**CASE["expected"], "key_facts": ["medical certificate is required"]}}
    answer = "Yes, you must bring a doctor's note (medical certificate)."
    assert not facts.fact_in_text("medical certificate is required", answer), "precondition: code can't match"
    stub({"judge_claims": {"unsupported_claims": []},
          "judge_fact": {"states_fact": True, "answer_span": "you must bring a doctor's note (medical certificate)"}})
    r = judge.score(cert, _trace(answer, citations=["leave_policy.md#0"]), Idx(CHUNKS))
    assert r["passed"] and r["facts"][0]["method"] == "llm", r["facts"]


def test_judge_claims_must_be_quoted_and_unsupported():
    stub({"judge_claims": {"unsupported_claims": ["You also get 45 bonus days", "never said this", "12 days"]}})
    r = judge.score(CASE, _trace("You get 12 days. You also get 45 bonus days.", citations=["leave_policy.md#0"]),
                    Idx(CHUNKS))
    assert r["unsupported_claims"] == ["You also get 45 bonus days"], r
    assert set(r["judge_claims_rejected"]) == {"never said this", "12 days"}
    assert not r["passed"] and r["failure"] == "hallucination"


def test_claims_judge_sees_the_question():
    calls = stub({"judge_claims": {"unsupported_claims": []}})
    judge.score(CASE, _trace("You get 12 days.", citations=["leave_policy.md#0"]), Idx(CHUNKS))
    sent = [v for n, v in calls if n == "judge_claims"]
    assert sent and sent[0]["question"] == CASE["question"], "user-supplied numbers must count as given (C01)"


def test_judge_grounding():
    stub({"judge_claims": {"unsupported_claims": []}})
    r = judge.score(CASE, _trace("You get 12 days.", citations=["travel_policy.md#0"]), Idx(CHUNKS))
    assert not r["passed"] and r["failure"] == "ungrounded"
    tool_case = {**CASE, "expected": {**CASE["expected"], "tool": "calculator"}}
    r = judge.score(tool_case, _trace("12 days", tools=["calculator"]), Idx(CHUNKS))
    assert r["passed"] and r["tool_used_as_expected"] is True


def test_scorecard_counts():
    rs = [{"type": "answerable", "passed": True, "fact_recall": 1.0, "retrieval_hit": True, "agent_llm_calls": 1},
          {"type": "answerable", "passed": False, "failure": "wrong_refusal", "fact_recall": 0.0,
           "retrieval_hit": False, "agent_llm_calls": 1},
          {"type": "out_of_scope", "passed": True, "agent_llm_calls": 0}]
    card = judge.scorecard(rs)
    assert card["pass_rate"] == 0.667 and card["failures"] == {"wrong_refusal": 1}
    assert card["wrong_refusal_rate"] == 0.5 and card["refusal_accuracy"] == 1.0


def test_selftest_detects_a_judge_that_says_yes_to_everything():
    cases = [{**CASE, "expected": {**CASE["expected"], "key_facts": ["12 days"]}}]
    stub({"judge_fact": {"states_fact": True, "answer_span": ""}, "judge_claims": {"unsupported_claims": []}})
    st = judge.judge_selftest(cases, Idx(CHUNKS))
    # number_changed and fabricated_claim need a flagged claim; a claims judge that never flags fails them.
    assert st["claim_verdict_accuracy"] < 1.0 and st["fact_verdict_accuracy"] == 1.0, st
    assert st["accuracy"] < 1.0 and st["correct"] < st["probes"], "reported accuracy must include claim verdicts"


def test_prompts_fill():
    for name, vals in {
        "eval_answerable": dict(audience="a", summary="s", chunk_id="c", passage="p", avoid="", others="o"),
        "eval_multi": dict(audience="a", summary="s", id_a="a", passage_a="p", id_b="b", passage_b="q", avoid="", doc_a="x", doc_b="y"),
        "eval_ambiguous": dict(question="q"),
        "eval_refuse": dict(audience="a", summary="s", refuse_topics="t", n_unrelated="2"),
        "eval_calc": dict(audience="a", chunk_id="c", passage="p", others="o"),
        "eval_check_rewrite": dict(original="o", rewrite="r"),
        "eval_solve_calc": dict(passage="p", question="q"),
        "judge_fact": dict(question="q", fact="f", answer="a", source="s"),
        "judge_claims": dict(passages="p", tool_results="t", answer="a", question="q"),
    }.items():
        assert "$" not in common.prompt(name, **vals), name


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
