"""Offline self-check for the runtime spine. No Ollama needed: embeddings are a
deterministic bag-of-words hash and the LLM is stubbed.

    python tests/test_phase1.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from runtime import llm, rag, runner, schema, tools  # noqa: E402

SMOKE = ROOT / "examples" / "smoke"


def fake_embed(texts, kind="document"):
    vecs = []
    for t in texts:
        v = np.zeros(256, dtype=np.float32)
        for w in t.lower().split():
            w = w.strip(".,:;()#?")
            if len(w) > 2:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
        vecs.append(v.tolist())
    return vecs


def test_chunking():
    text = "\n\n".join(" ".join(f"w{p}_{i}" for i in range(40)) for p in range(10))  # 10 paras x 40 words
    chunks = rag.chunk_text(text, chunk_words=100, overlap=20)
    assert all(len(c.split()) <= 120 for c in chunks), "chunks overflow"
    assert "w0_0" in chunks[0] and "w9_39" in chunks[-1], "text lost at the edges"
    long = " ".join(f"x{i}" for i in range(250))
    parts = rag.chunk_text(long, chunk_words=100, overlap=20)
    assert parts[1].split()[0] == "x80", "overlap window wrong"
    assert parts[-1].split()[-1] == "x249"
    try:
        rag.chunk_text("a b", 10, 10)
        raise AssertionError("overlap >= chunk size must fail")
    except ValueError:
        pass


def test_retrieval_ranks_right_doc():
    idx = rag.Index.from_folder(SMOKE / "docs", 200, 30, embed_fn=fake_embed)
    assert any(c["doc"] == "leave_entitlements.csv" for c in idx.chunks), "CSV not indexed"
    top = idx.search("daily allowance for international travel", k=1)[0]
    assert top["doc"] == "travel_policy.md", top
    assert idx.search("daily allowance", k=3, min_score=1.01) == [], "min_score not applied"


def test_calculator_is_safe():
    assert tools.calculator("(12 * 450) * 1.18")["result"] == 6372.0
    assert tools.calculator("2 ** 10")["result"] == 1024
    for evil in ("__import__('os').system('x')", "open('/etc/passwd')", "a + 1", "9 ** 999999"):
        assert "error" in tools.calculator(evil), evil
    assert "error" in tools.calculator("1/0")


def test_csv_lookup_confined_to_docs_dir():
    docs = SMOKE / "docs"
    r = tools.csv_lookup("leave_entitlements.csv", "grade", "g3", docs_dir=docs)
    assert r["matches"] == 1 and r["rows"][0]["annual_leave_days"] == "24"
    assert "error" in tools.csv_lookup("leave_entitlements.csv", "nope", "y", docs_dir=docs)
    # A valid CSV just outside the docs folder must still be unreachable.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "docs").mkdir()
        (Path(tmp) / "secret.csv").write_text("k,v\nsalary,999\n")
        r = tools.csv_lookup("../secret.csv", "k", "salary", docs_dir=Path(tmp) / "docs")
        assert "error" in r and "rows" not in r, r


def test_tool_gate():
    assert "error" in tools.call("weather", {"city": "Chennai"}, allowed=["calculator"])
    assert tools.call("calculator", {"expression": "1+1"}, allowed=["calculator"]) == {"result": 2}


def test_schema_checker():
    d = json.loads((SMOKE / "agent_def.json").read_text())
    s = schema.load("agent_def")
    assert schema.errors(d, s) == []
    bad = {**d, "tools": ["weather", "shell"], "retrieval": {**d["retrieval"], "k": 0}}
    del bad["system_prompt"]
    errs = " | ".join(schema.errors(bad, s))
    assert "system_prompt" in errs and "'shell'" in errs and "minimum" in errs, errs
    assert schema.errors({**d, "retrieval": {**d["retrieval"], "k": True}}, s), "bool must not pass as integer"


def _agent(**overrides):
    d = {**json.loads((SMOKE / "agent_def.json").read_text()), **overrides}
    r = d["retrieval"]
    idx = rag.Index.from_folder(SMOKE / "docs", r["chunk_words"], r["overlap"], embed_fn=fake_embed)
    return runner.Agent(d, base_dir=SMOKE, index=idx)


def _no_llm(*a, **k):
    raise AssertionError("LLM must not be called")


def test_deterministic_refusal_without_llm():
    no_hits = {"chunk_words": 200, "overlap": 30, "k": 4, "min_score": 0.99}
    for tool_set in ([], ["csv_lookup", "calculator"]):  # corpus-bound tools can't rescue an empty context
        agent = _agent(tools=tool_set, retrieval=no_hits)
        llm.chat = _no_llm
        res = agent.answer("what is the capital of peru")
        assert res["refused"] and res["refusal_source"] == "no_context", tool_set

    agent = _agent(tools=["current_date"], retrieval=no_hits)  # a context-free tool must get its chance
    llm.chat = lambda *a, **k: {"role": "assistant", "content": '{"answer": "Wednesday", "citations": [], "refused": false}'}
    assert agent.answer("what day is it")["refused"] is False


def test_short_tags_map_to_chunk_ids():
    agent = _agent(tools=[], retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    hits = agent.index.search("sick leave days", k=2)
    llm.chat = lambda *a, **k: {"role": "assistant", "content": json.dumps(
        {"answer": "12 days.", "citations": ["S2", "[S1]", 2, "S9"], "refused": False})}
    res = agent.answer("sick leave days")
    assert res["citations"] == [hits[1]["id"], hits[0]["id"]], res["citations"]
    assert "invalid_citation" in res["violations"]  # S9 was never shown


def test_csv_schema_lists_real_files():
    desc = _agent().tool_schemas[0]["function"]["description"]
    assert "leave_entitlements.csv (columns: grade, title_band" in desc, desc


def _scripted(loop_reply, final='{"answer": "2", "citations": [], "refused": false}', log=None):
    """Stub LLM: stage 1 (JSON, no tools) asks for a tool; tool turns return loop_reply;
    free-text turns without tools return prose; later JSON turns return `final`."""
    state = {"stage1": True}

    def chat(msgs, tools=None, json_mode=False, **k):
        if log is not None:
            log.append({"tools": bool(tools), "json": json_mode})
        if json_mode and state["stage1"]:
            state["stage1"] = False
            return {"role": "assistant", "content": '{"need_tool": "calculator"}'}
        if tools:
            return loop_reply
        if json_mode:
            return {"role": "assistant", "content": final}
        return {"role": "assistant", "content": "It is 2."}
    return chat


def test_tool_loop_dedupes_and_terminates():
    agent = _agent(retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    loop = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "calculator", "arguments": {"expression": "1+1"}}}]}
    log = []
    llm.chat = _scripted(loop, log=log)  # model asks for the same tool forever while tools are offered
    res = agent.answer("what is 1+1 days of leave")
    assert len(res["tool_calls"]) == 1, "identical call should execute once"
    tool_turns = [e for e in log if e["tools"]]
    assert len(tool_turns) == runner.MAX_TOOL_ROUNDS, f"loop not bounded: {log}"
    assert not log[-2]["tools"] and log[-1]["json"], f"last round must withhold tools, then finalize: {log}"
    assert res["answer"] == "2" and "uncited_answer" not in res["violations"], res  # tool-backed
    assert "bad_json" not in res["violations"], "prose during the tool loop is by design"


def test_stage1_answer_never_offers_tools():
    agent = _agent(retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    real = agent.index.search("sick leave days", k=1)[0]["id"]
    log = []

    def chat(msgs, tools=None, json_mode=False, **k):
        log.append(bool(tools))
        return {"role": "assistant", "content": '{"answer": "12 days", "citations": ["S1"], "refused": false}'}
    llm.chat = chat
    res = agent.answer("sick leave days")
    assert log == [False], f"plain question must cost one tool-free call, got {log}"
    assert res["citations"] == [real] and res["tool_calls"] == []


def test_contract_enforcement():
    agent = _agent(tools=[], retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    real = agent.index.search("sick leave days", k=2)[0]["id"]
    replies = iter([{"role": "assistant", "content": json.dumps(
        {"answer": "12 days.", "citations": [real, "made_up.md#9"], "refused": False})}])
    llm.chat = lambda *a, **k: next(replies)
    res = agent.answer("sick leave days")
    assert res["citations"] == [real] and "invalid_citation" in res["violations"], res

    replies = iter([{"role": "assistant", "content": '{"answer": "12 days.", "citations": [], "refused": false}'}])
    res = agent.answer("sick leave days")
    assert "uncited_answer" in res["violations"], res


def test_empty_answer_becomes_flagged_refusal():
    agent = _agent(tools=[], retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    llm.chat = lambda *a, **k: {"role": "assistant", "content": '{"answer": "", "citations": ["S1"], "refused": false}'}
    res = agent.answer("what is my colleague's salary")
    assert res["refused"] and res["answer"] == agent.d["output_contract"]["refusal_message"], res
    assert res["refusal_source"] == "empty_answer" and "empty_answer" in res["violations"] and res["citations"] == []


def test_tool_loop_executes_allowed_tool():
    agent = _agent(retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    calls = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "calculator", "arguments": {"expression": "2.0 * 6"}}},
        {"function": {"name": "weather", "arguments": {"city": "Oslo"}}}]}
    done = {"role": "assistant", "content": "12 days"}
    turns = iter([calls, done])
    base = _scripted(None, final="```json\n{\"answer\": \"12 days\", \"citations\": [], \"refused\": false}\n```")
    llm.chat = lambda msgs, tools=None, json_mode=False, **k: next(turns) if tools else base(msgs, None, json_mode)
    res = agent.answer("G3 manager leave accrued after 6 months?")
    calc, wx = res["tool_calls"]
    assert calc["result"] == {"result": 12.0}
    assert "not available" in wx["result"]["error"], "disallowed tool must be blocked"
    assert res["answer"] == "12 days" and "bad_json" not in res["violations"]


def test_bad_json_is_repaired_and_recorded():
    agent = _agent(tools=[], retrieval={"chunk_words": 200, "overlap": 30, "k": 2, "min_score": 0.0})
    replies = iter([{"role": "assistant", "content": "Sick leave is 12 days a year."},
                    {"role": "assistant", "content": '{"answer": "12 days", "citations": [], "refused": false}'}])
    llm.chat = lambda *a, **k: next(replies)
    res = agent.answer("sick leave days")
    assert "bad_json" in res["violations"] and res["answer"] == "12 days", res


def test_page_furniture_stripped():
    pages = [f"ACME Corp - Confidential\nSection {i}: real content line {i} about leave.\n\nPage {i} of 4"
             for i in range(1, 5)]
    out = rag.strip_page_furniture("\f".join(pages) + "\f")
    assert "Confidential" not in out and "Page 3 of 4" not in out, out
    assert all(f"real content line {i}" in out for i in range(1, 5)), "content lost"
    long_repeat = "This sentence is a long legitimate clause that appears in every single section of the policy text."
    kept = rag.strip_page_furniture("\f".join(f"{long_repeat}\nunique {i}" for i in range(4)))
    assert kept.count(long_repeat) == 4, "long repeated lines are content, not furniture"
    assert rag.strip_page_furniture("one page only\nPage 1") == "one page only\nPage 1"
    rows = "\f".join(f"Grade G{i} | 2{i} days\nGrade G{i + 4} | 3{i} days\n{i}" for i in range(1, 5))
    out = rag.strip_page_furniture(rows)
    assert all(f"Grade G{i} | 2{i} days" in out for i in range(1, 5)), "table rows differing by a number are content"
    assert "\n1\n" not in f"\n{out}\n" and "\n3\n" not in f"\n{out}\n", "bare page numbers should go"


def test_llm_errors_are_actionable():
    old = llm.HOST
    llm.HOST = "http://127.0.0.1:1"
    try:
        for fn in (lambda: llm.chat([{"role": "user", "content": "hi"}]), lambda: llm.embed(["x"]), llm.preflight):
            try:
                fn()
                raise AssertionError("expected LLMError")
            except llm.LLMError as e:
                assert "ollama serve" in str(e), e
    finally:
        llm.HOST = old

    class Tags:
        def json(self):
            return {"models": [{"name": "qwen3.5-4b-8k:latest"}]}
    real_get = llm.requests.get
    llm.requests.get = lambda *a, **k: Tags()
    try:
        llm.preflight(("qwen3.5-4b-8k", "nomic-embed-text"))
        raise AssertionError("missing embed model not detected")
    except llm.LLMError as e:
        assert "ollama pull nomic-embed-text" in str(e) and "qwen" not in str(e).split("Run:")[0], e
    finally:
        llm.requests.get = real_get


def test_runner_cli_exits_cleanly_without_ollama():
    import subprocess
    env = {**__import__("os").environ, "OLLAMA_HOST": "http://127.0.0.1:1"}
    p = subprocess.run([sys.executable, "-m", "runtime.runner", str(SMOKE / "agent_def.json"), "--ask", "x"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "Traceback" not in p.stderr and "ollama serve" in p.stderr, p.stderr


def test_parse_json_variants():
    assert llm.parse_json('{"a": 1}') == {"a": 1}
    assert llm.parse_json('Sure!\n```json\n{"a": 2}\n```') == {"a": 2}
    assert llm.parse_json('blah {"a": 3} trailing') == {"a": 3}
    assert llm.parse_json('[1, 2]') == [1, 2]


if __name__ == "__main__":
    original_chat = llm.chat
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        llm.chat = original_chat
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
