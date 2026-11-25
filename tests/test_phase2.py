"""Offline self-check for intake + generator. The factory LLM is stubbed per prompt name, and
embeddings use the same bag-of-words fake as Phase 1.

    python tests/test_phase2.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from factory import common, generator, groundability, intake  # noqa: E402
from runtime import rag, runner, schema  # noqa: E402
from tests.test_phase1 import SMOKE, fake_embed  # noqa: E402

DOCS = SMOKE / "docs"
INV = [
    {"name": "leave_policy.md", "kind": "md", "words": 150, "summary": "Leave rules.", "topics": ["sick leave"]},
    {"name": "travel_policy.md", "kind": "md", "words": 120, "summary": "Travel rules.", "topics": ["allowance"]},
    {"name": "leave_entitlements.csv", "kind": "csv", "words": 60, "summary": "Leave days by grade.",
     "topics": ["grades"], "columns": ["grade", "annual_leave_days"], "rows": 5},
]
REQ = {
    "name": "HR Policy Assistant!", "summary": "Answers shore-staff HR policy questions.",
    "audience": "shore staff", "tone": "plain", "answer_length": "short",
    "must_answer_topics": [
        {"topic": "Sick leave", "details": "sick leave days and certificates", "source_docs": ["leave_policy.md"]},
        {"topic": "Annual leave by grade", "details": "entitlement per grade", "source_docs": ["leave_entitlements.csv"]},
        {"topic": "Maternity leave", "details": "maternity leave rules", "source_docs": []},
    ],
    "must_refuse_topics": [{"topic": "Individual salaries", "reason": "confidential"}],
    "assumptions": [], "brief": "I need an assistant that answers HR policy questions for shore staff",
}


def stub(responses):
    """Replace common.ask_json with canned outputs keyed by prompt name; run the real check."""
    calls = []

    def ask_json(_prompt, check=None, temperature=0.0, **values):
        name = _prompt
        calls.append((name, values))
        out = responses[name](values) if callable(responses[name]) else responses[name]
        err = check(out) if check else None
        if err:
            raise ValueError(f"stub output for {name} failed check: {err}")
        return out
    for mod in (common, intake, generator, groundability):
        mod.ask_json = ask_json
    return calls


def test_question_cap_dedupe_and_defaults():
    qs = [{"question": f"Q{i}?", "why": "w", "default_assumption": f"d{i}"} for i in range(8)]
    qs.insert(1, {"question": "q0?", "why": "dup", "default_assumption": "x"})
    stub({"intake_questions": {"questions": qs}})
    out = intake.questions("brief", INV)
    assert len(out) == intake.MAX_QUESTIONS and [q["question"] for q in out][:2] == ["Q0?", "Q1?"], out

    clar = intake.interview(out[:3], intake.file_answerer(["Refuse it.", "", None]))
    assert clar[0] == {"question": "Q0?", "answer": "Refuse it.", "source": "requester"}
    assert clar[1]["source"] == "assumed" and clar[1]["answer"] == "d1"
    assert clar[2]["source"] == "assumed"


def test_question_without_default_is_rejected():
    stub({"intake_questions": {"questions": [{"question": "Q?", "why": "w"}]}})
    try:
        intake.questions("brief", INV)
        raise AssertionError("a question with no default assumption must fail the check")
    except ValueError:
        pass


def test_requirements_drop_unknown_docs_and_validate():
    bad = json.loads(json.dumps(REQ))
    bad["must_answer_topics"][0]["source_docs"] = ["leave_policy.md", "imaginary.pdf"]
    stub({"intake_requirements": bad})
    req = intake.requirements("brief", INV, [])
    assert req["must_answer_topics"][0]["source_docs"] == ["leave_policy.md"]
    assert any("imaginary.pdf" in a for a in req["assumptions"])
    assert schema.errors(req, schema.load("requirements")) == []

    broken = {**REQ, "answer_length": "epic"}
    stub({"intake_requirements": broken})
    try:
        intake.requirements("brief", INV, [])
        raise AssertionError("invalid answer_length must fail validation")
    except ValueError:
        pass


class _TopicIdx:
    """Index stub: hits per topic label found in the query, honouring k and min_score."""
    def __init__(self, by_topic):
        self.by_topic = by_topic

    def search(self, q, k=4, min_score=0.0):
        for label, hits in self.by_topic.items():
            if q.startswith(label + ":"):
                return [h for h in hits if h["score"] >= min_score][:k]
        return []


def _hit(i, doc, text, score=0.8):
    return {"id": f"{doc}#{i}", "doc": doc, "text": text, "score": score}


HR_IDX = _TopicIdx({
    "Sick leave": [_hit(0, "leave_policy.md", "Emergency leave can be applied for retrospectively within 3 "
                                              "working days of returning. 12 days of sick leave per year.")],
    "Annual leave by grade": [_hit(0, "leave_entitlements.csv", "grade: G3; annual_leave_days: 24; "
                                                                "monthly_accrual_days: 2.0")],
    "Maternity leave": [_hit(0, "travel_policy.md", "Daily allowance of INR 2,500 per day.")],  # undocumented topic
})


def _req(**over):
    r = json.loads(json.dumps(REQ))
    r.update(over)
    return r


def test_tools_need_both_a_requirement_and_document_evidence():
    req = _req(clarifications=[{"answer": "It will calculate accrued leave and check deadlines."}])
    chosen, rationale, log_ = generator.select_tools(req, INV, HR_IDX, ceiling=0.6)
    assert chosen == ["csv_lookup", "calculator", "current_date"], log_
    by = {d["tool"]: d for d in log_}
    assert "leave_entitlements.csv" in by["csv_lookup"]["need_signal"]
    assert by["calculator"]["evidence"].split(":")[0] in {"leave_policy.md#0", "leave_entitlements.csv#0"}, \
        "evidence must cite a real passage id"
    csv_only = _TopicIdx({"Annual leave by grade": HR_IDX.by_topic["Annual leave by grade"]})
    req_csv = _req(clarifications=[{"answer": "calculate accrued leave"}],
                   must_answer_topics=[REQ["must_answer_topics"][1]])
    chosen_csv, _, log_csv = generator.select_tools(req_csv, INV, csv_only, ceiling=0.6)
    assert "calculator" in chosen_csv, f"snake_case CSV column monthly_accrual_days is evidence: {log_csv}"
    assert "within 3" in by["current_date"]["evidence"]
    assert by["weather"]["attached"] is False and "never call for it" in by["weather"]["reason"]
    assert set(rationale) == set(chosen)


def test_no_need_signal_means_no_tool_even_with_evidence():
    req = _req(brief="Answer questions about leave policy.", summary="Leave policy questions.",
               must_answer_topics=[{"topic": "Sick leave", "details": "sick leave rules", "source_docs": ["leave_policy.md"]}])
    chosen, _, log_ = generator.select_tools(req, INV, HR_IDX, ceiling=0.6)
    assert "current_date" not in chosen and "calculator" not in chosen, log_


def test_need_without_evidence_is_not_enough():
    faq = _TopicIdx({"Build requirements": [_hit(0, "assignment.pdf", "All nine requirements are mandatory. "
                                                                     "Generate at least 20 eval cases.")]})
    req = _req(brief="Candidates ask how many requirements there are and the deadline.",
               must_answer_topics=[{"topic": "Build requirements", "details": "how many items, what to build",
                                    "source_docs": ["assignment.pdf"]}])
    chosen, _, log_ = generator.select_tools(req, [d for d in INV if d["kind"] != "csv"], faq, ceiling=0.6)
    assert chosen == [], log_
    calc = next(d for d in log_ if d["tool"] == "calculator")
    assert calc["need_signal"] and "anything to work on" in calc["reason"], calc


def test_undocumented_and_weak_passages_are_not_evidence():
    # Only the undocumented "Maternity leave" topic has money in its passages: must not count.
    req = _req(clarifications=[{"answer": "calculate costs"}], must_answer_topics=[
        {"topic": "Sick leave", "details": "sick leave rules", "source_docs": ["leave_policy.md"]},
        {"topic": "Maternity leave", "details": "allowance amounts", "source_docs": []}])
    idx = _TopicIdx({**HR_IDX.by_topic, "Sick leave": [_hit(0, "leave_policy.md", "12 days of sick leave.")]})
    assert "calculator" not in generator.select_tools(req, INV, idx, ceiling=0.6)[0]

    weak = _TopicIdx({"Sick leave": [_hit(0, "leave_policy.md", "INR 2,500 per day", score=0.5)]})
    req = _req(clarifications=[{"answer": "calculate costs"}], must_answer_topics=[
        {"topic": "Sick leave", "details": "sick pay amounts", "source_docs": ["leave_policy.md"]}])
    assert "calculator" not in generator.select_tools(req, INV, weak, ceiling=0.6)[0], "below-ceiling passage"


def test_csv_needs_a_supported_topic_sourced_from_it():
    req = _req(must_answer_topics=[{"topic": "Sick leave", "details": "rules", "source_docs": ["leave_policy.md"]}])
    chosen, _, _ = generator.select_tools(req, INV, HR_IDX, ceiling=0.6)  # CSV exists but nothing relies on it
    assert "csv_lookup" not in chosen


def test_weather_only_when_requested_never_for_terms_and_conditions():
    hr = _req(brief="HR assistant: explain the terms and conditions of employment for shore staff.")
    assert "weather" not in generator.select_tools(hr, INV, HR_IDX, ceiling=0.6)[0]

    port = _req(brief="assistant for port captains that checks sea conditions and weather before berthing",
                must_answer_topics=REQ["must_answer_topics"] + [
                    {"topic": "Berthing weather", "details": "current wind at the port", "source_docs": []}])
    chosen = generator.select_tools(port, INV, HR_IDX, ceiling=0.6)[0]
    assert "weather" in chosen
    p = generator.system_prompt(port, "x", generator.tool_served_topics(port, chosen))
    scope, _, uncovered = p.partition("Your documents do not cover")
    assert "Berthing weather" in scope and "Berthing weather" not in uncovered, "tool-served topic must stay in scope"
    assert "Maternity leave" in uncovered


def test_date_tool_serves_a_today_topic_but_not_an_undocumented_deadline():
    req = _req(brief="FAQ bot.", summary="FAQ.", must_answer_topics=[
        {"topic": "Deadline", "details": "the submission deadline", "source_docs": []},
        {"topic": "Sick leave", "details": "rules", "source_docs": ["leave_policy.md"]}])
    idx = _TopicIdx({"Sick leave": [_hit(0, "leave_policy.md", "12 days of sick leave.")]})
    assert "current_date" not in generator.select_tools(req, INV, idx, ceiling=0.6)[0]

    req["must_answer_topics"].append({"topic": "Today", "details": "what is today's date", "source_docs": []})
    chosen, _, log_ = generator.select_tools(req, INV, idx, ceiling=0.6)
    assert "current_date" in chosen and generator.tool_served_topics(req, chosen) == ["Today"], log_


def test_quote_verification():
    passages = ["Employees receive 12 days of paid sick leave per calendar year."]
    assert groundability.quote_found("Employees receive 12 days of paid sick leave", passages)
    assert groundability.quote_found("employees  receive 12 days paid sick-leave per year", passages), "tolerate drift"
    assert not groundability.quote_found("The salary for this role is 7 LPA", passages)
    assert not groundability.quote_found("sick", passages), "too short to verify"


class _Idx:
    """Index stub: fixed hits for any query."""
    def __init__(self, hits):
        self.hits = hits

    def search(self, q, k=3):
        return self.hits[:k]


def test_groundability_gate_quote_check_and_rewrite():
    req = json.loads(json.dumps(REQ))
    req["must_answer_topics"][2]["source_docs"] = ["leave_policy.md"]  # requirements step lied (like salary)
    hits = [{"id": "leave_policy.md#0", "doc": "leave_policy.md", "score": 0.8,
             "text": "Employees receive 12 days of paid sick leave per calendar year."},
            {"id": "travel_policy.md#0", "doc": "travel_policy.md", "score": 0.5, "text": "Daily allowance INR 2,500."}]
    verdicts = iter([
        {"verdict": "supported", "quote": "Employees receive 12 days of paid sick leave", "missing": ""},
        {"verdict": "supported", "quote": "Grade G3 gets 24 days", "missing": ""},      # fabricated quote
        {"verdict": "supported", "quote": "Maternity leave is 26 weeks", "missing": ""},  # fabricated quote
    ])
    stub({"ground_check": lambda v: next(verdicts)})
    out = groundability.guard(req, _Idx(hits), ceiling=0.6)
    flags = {f["topic"]: f for f in out["groundability"]["flags"]}
    assert flags["Sick leave"]["verdict"] == "supported"
    assert out["must_answer_topics"][0]["source_docs"] == ["leave_policy.md"], "only docs above the ceiling"
    assert flags["Annual leave by grade"]["method"] == "quote_not_in_passages"
    assert flags["Maternity leave"]["verdict"] == "unsupported" and out["must_answer_topics"][2]["source_docs"] == []
    assert "overruled" in out["groundability"]["summary"] and "Maternity leave" in out["groundability"]["summary"]

    stub({"ground_check": lambda v: (_ for _ in ()).throw(AssertionError("gate must not call the LLM"))})
    weak = [{**hits[0], "score": 0.4}]
    out = groundability.guard(json.loads(json.dumps(REQ)), _Idx(weak), ceiling=0.6)
    assert all(f["method"] == "retrieval_gate" and f["verdict"] == "unsupported" for f in out["groundability"]["flags"])


def test_system_prompt_keeps_every_rule():
    p = generator.system_prompt(REQ, "You are a helpful HR assistant.")
    assert p.startswith("You are a helpful HR assistant.")
    assert "Sick leave" in p and "Annual leave by grade" in p
    assert "Individual salaries" in p and "confidential" in p
    scope, _, rest = p.partition("Your documents do not cover")
    assert "Maternity leave" not in scope and "Maternity leave" in rest, "uncovered topic must be marked, not in scope"


def test_calibration_tracks_corpus():
    idx = rag.Index.from_folder(DOCS, 250, 40, embed_fn=fake_embed)
    t, info = generator.calibrate(idx, REQ)
    assert info["in_scope_source"] == "topic_labels", "no sample questions -> label fallback"
    assert set(info["in_scope_scores"]) == {"Sick leave", "Annual leave by grade"}, "uncovered topics excluded"
    if info["separable"]:
        assert t == round(info["off_topic_max"] + generator.MARGIN, 3)
    else:
        import statistics
        assert t == round(max(0.0, min(info["in_scope_min"] - generator.MARGIN,
                                       statistics.median(info["off_topic_scores"].values()))), 3)

    class FixedIndex:  # overlap case: off-topic probes score above the weakest real topic
        def search(self, q, k=1):
            return [{"score": 0.5 if q in generator.OFF_TOPIC_PROBES else 0.45}]
    t, info = generator.calibrate(FixedIndex(), REQ)
    assert not info["separable"] and t == 0.43 and "recall floor" in info["gate_role"], (t, info)

    class Clean:
        def search(self, q, k=1):
            return [{"score": 0.4 if q in generator.OFF_TOPIC_PROBES else 0.8}]
    t, info = generator.calibrate(Clean(), REQ)
    assert info["separable"] and t == 0.42, (t, info)


def test_calibration_measures_user_questions_not_labels():
    # Labels score high (0.75) but real questions score lower (0.55), overlapping the probes (<=0.6).
    req = json.loads(json.dumps(REQ))
    req["must_answer_topics"][0]["sample_questions"] = ["how many sick days?", "do I need a doctor's note?"]
    req["must_answer_topics"][2]["sample_questions"] = ["undocumented topic question"]  # must be ignored

    class Idx:
        def search(self, q, k=1):
            if q in generator.OFF_TOPIC_PROBES:
                return [{"score": 0.6}]
            if q == "undocumented topic question":
                return [{"score": 0.1}]
            return [{"score": 0.55 if "?" in q else 0.75}]
    t, info = generator.calibrate(Idx(), req)
    assert info["in_scope_source"] == "sample_questions" and set(info["in_scope_scores"]) == {
        "how many sick days?", "do I need a doctor's note?"}, info
    assert not info["separable"] and t == 0.53, "gate must sit under the real questions, not the labels"


def test_groundability_keeps_sample_questions_only_for_supported_topics():
    hits = [{"id": "leave_policy.md#0", "doc": "leave_policy.md", "score": 0.8,
             "text": "Employees receive 12 days of paid sick leave per calendar year."}]
    replies = iter([
        {"verdict": "supported", "quote": "Employees receive 12 days of paid sick leave",
         "sample_questions": ["How many sick days do I get?", "Is sick leave paid?", "extra one"]},
        {"verdict": "unsupported", "quote": "", "missing": "grades", "sample_questions": ["leak?"]},
        {"verdict": "supported", "quote": "invented words never present here", "sample_questions": ["leak2?"]},
    ])
    stub({"ground_check": lambda v: next(replies)})
    out = groundability.guard(json.loads(json.dumps(REQ)), _Idx(hits), ceiling=0.6)
    qs = [t["sample_questions"] for t in out["must_answer_topics"]]
    assert qs == [["How many sick days do I get?", "Is sick leave paid?"], [], []], qs


def test_generate_end_to_end_offline():
    import tempfile
    stub({
        "gen_system_prompt": {"persona": "You are the HR helper for shore staff.",
                              "refusal_message": "Sorry, that's outside the HR policies I have.",
                              "description": "Answers shore-staff HR policy questions."},
        "gen_tools": {"decisions": [{"tool": "csv_lookup", "attach": True,
                                     "needed_for_topic": "Annual leave by grade", "reason": "grade table"}]},
    })
    real_index = rag.Index.from_folder
    rag.Index.from_folder = classmethod(lambda cls, f, c, o, embed_fn=None: real_index(f, c, o, embed_fn=fake_embed))
    try:
        with tempfile.TemporaryDirectory() as out:
            d = generator.generate(REQ, INV, DOCS, out)
            assert d["name"] == "hr-policy-assistant" and d["tools"] == ["csv_lookup"]
            assert d["output_contract"]["max_words"] == 80
            assert schema.errors(d, schema.load("agent_def")) == []
            Path(out, "agent_def.json").write_text(json.dumps(d))
            agent = runner.Agent.load(Path(out, "agent_def.json"))  # docs_dir resolves relative to the def
            assert agent.docs_dir == DOCS.resolve()
            # Committed demo runs must work from any clone: never bake in an absolute path.
            assert not Path(d["docs_dir"]).is_absolute(), d["docs_dir"]
    finally:
        rag.Index.from_folder = real_index


def test_requirements_markdown_renders():
    req = {**REQ, "clarifications": [{"question": "Q?", "answer": "A", "source": "assumed"}],
           "documents": [{"name": "leave_policy.md", "kind": "md", "summary": "s"}]}
    md = intake.render_markdown(req)
    assert "| Maternity leave | maternity leave rules | **none** |" in md and "A (assumed)" in md


def test_prompts_fill_without_leftover_placeholders():
    for name, vals in {
        "intake_summarize": dict(name="a", kind="md", extra="", excerpt="x"),
        "intake_questions": dict(brief="b", inventory="i", max_questions="5"),
        "intake_requirements": dict(brief="b", inventory="i", clarifications=[]),
        "gen_system_prompt": dict(requirements={}),
        "ground_check": dict(topic="t", details="d", passages="p"),
    }.items():
        text = common.prompt(name, **vals)
        assert "$" not in text.replace("$$", ""), f"unfilled placeholder in {name}"


if __name__ == "__main__":
    original = common.ask_json
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    for mod in (common, intake, generator):
        mod.ask_json = original
    print(f"\n{len(tests)} passed")
