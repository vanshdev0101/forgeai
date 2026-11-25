"""Mutation check for the Phase 2 suite: break each guard in turn; tests/test_phase2.py must fail every time.

    python tests/mutate_phase2.py
"""
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
MUTANTS = [
    ("question cap removed", "factory/intake.py", "return qs[:MAX_QUESTIONS]", "return qs"),
    ("dedupe removed", "factory/intake.py", "if key not in seen:", "if True:"),
    ("default not required", "factory/intake.py",
     "if not isinstance(q, dict) or not q.get(\"question\") or not q.get(\"default_assumption\"):",
     "if not isinstance(q, dict) or not q.get(\"question\"):"),
    ("assumed passed off as requester", "factory/intake.py",
     "\"source\": \"requester\" if ans else \"assumed\"", "\"source\": \"requester\""),
    ("unknown docs kept", "factory/intake.py",
     "t[\"source_docs\"] = [s for s in t[\"source_docs\"] if s in names]", "pass"),
    ("tools: need not required", "factory/generator.py",
     "attach = bool(need and feas) or bool(served)", "attach = bool(feas) or bool(served)"),
    ("tools: evidence not required", "factory/generator.py",
     "attach = bool(need and feas) or bool(served)", "attach = bool(need) or bool(served)"),
    ("tools: undocumented topics give evidence", "factory/generator.py",
     "grounded = [t for t in req[\"must_answer_topics\"] if t[\"source_docs\"]]",
     "grounded = req[\"must_answer_topics\"]"),
    ("tools: below-ceiling passages count", "factory/generator.py",
     "k=4, min_score=ceiling):", "k=4, min_score=0.0):"),
    ("tools: csv attached without a supported csv topic", "factory/generator.py",
     "need = f\"supported topics sourced from {csv_docs}\" if csv_docs else None",
     "need = \"csv present\" if csv_files else None"),
    ("tools: weather without request", "factory/generator.py",
     "need = _first(WEATHER_WORDS, need_text)", "need = \"always\""),
    ("tools: bare 'conditions' is weather", "factory/generator.py",
     "r\"sea conditions|weather conditions|port conditions|monsoon)\\b\"", "r\"conditions|monsoon)\\b\""),
    ("tools: 'N days of' is a time window", "factory/generator.py",
     "r\"(in advance|before|after|from)|deadline", "r\"(in advance|before|after|of|from)|deadline"),
    ("tools: snake_case columns invisible", "factory/generator.py",
     "r\"piece|item|night|week|kg|litre)\\b|(?<![a-z])(monthly|daily|unit[_ ]price|price|\"\n"
     "                             r\"cost|rate)(?![a-z]))\"",
     "r\"piece|item|night|week|kg|litre)\\b|\\b(monthly|daily|unit[_ ]price|price|\"\n"
     "                             r\"cost|rate)\\b)\""),
    ("tools: clarifications ignored", "factory/generator.py",
     "parts += [c.get(\"answer\", \"\") for c in req.get(\"clarifications\", [])]", "pass"),
    ("uncovered topics put in scope", "factory/generator.py",
     "covered = [t for t in req[\"must_answer_topics\"] if t[\"source_docs\"] or t[\"topic\"] in tool_topics]",
     "covered = req[\"must_answer_topics\"]"),
    ("refuse list dropped", "factory/generator.py",
     "parts += [f\"- {t['topic']} ({t['reason']})\" for t in req[\"must_refuse_topics\"]]", "pass"),
    ("overlap branch removed", "factory/generator.py",
     "threshold = off_max + MARGIN if separable else max(", "threshold = off_max + MARGIN if True else max("),
    ("calib: median cap removed", "factory/generator.py",
     "min(on_min - MARGIN, statistics.median(off.values()))", "on_min - MARGIN"),
    ("margin dropped", "factory/generator.py",
     "threshold = off_max + MARGIN if separable else", "threshold = off_max if separable else"),
    ("uncovered topics calibrated", "factory/generator.py",
     "for t in req[\"must_answer_topics\"] if t[\"source_docs\"]}", "for t in req[\"must_answer_topics\"]}"),
    ("calib: labels instead of questions", "factory/generator.py",
     "for q in t.get(\"sample_questions\") or []:", "for q in []:"),
    ("calib: undocumented samples counted", "factory/generator.py",
     "    for t in req[\"must_answer_topics\"]:\n        if t[\"source_docs\"]:\n            for q in",
     "    for t in req[\"must_answer_topics\"]:\n        if True:\n            for q in"),
    ("ground: samples kept for unsupported", "factory/groundability.py",
     "if str(q).strip()][:2] if docs else []", "if str(q).strip()][:2]"),
    ("ground: sample cap removed", "factory/groundability.py",
     "if str(q).strip()][:2] if docs else []", "if str(q).strip()] if docs else []"),
    ("ground: retrieval gate removed", "factory/groundability.py", "if best < ceiling:", "if False:"),
    ("ground: quote check removed", "factory/groundability.py",
     "if verdict != \"unsupported\" and not quote_found(quote, [h[\"text\"] for h in hits]):", "if False:"),
    ("ground: claimed docs kept", "factory/groundability.py",
     "t[\"source_docs\"] = r[\"docs\"]", "pass"),
    ("ground: low-score docs counted", "factory/groundability.py",
     "docs = sorted({h[\"doc\"] for h in hits if h[\"score\"] >= ceiling})",
     "docs = sorted({h[\"doc\"] for h in hits})"),
    ("ground: quote threshold loosened", "factory/groundability.py", "QUOTE_MATCH = 0.7", "QUOTE_MATCH = 0.0"),
    ("tools: served topics ignored", "factory/generator.py",
     "and TOOL_PROVIDES.get(name, NEVER).search(f\"{t['topic']} {t['details']}\")]",
     "and False]"),
    ("tool-served topics refused", "factory/generator.py",
     "covered = [t for t in req[\"must_answer_topics\"] if t[\"source_docs\"] or t[\"topic\"] in tool_topics]",
     "covered = [t for t in req[\"must_answer_topics\"] if t[\"source_docs\"]]"),
    ("relative docs_dir broken", "factory/generator.py",
     "\"docs_dir\": os.path.relpath(Path(docs_dir).resolve(), Path(out_dir).resolve()),",
     "\"docs_dir\": str(docs_dir),"),
]
import os  # noqa: E402
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # stale .pyc made restored mutants linger


def run():
    return subprocess.run([sys.executable, "tests/test_phase2.py"], cwd=root, capture_output=True,
                          timeout=120, env=ENV).returncode


assert run() == 0, "clean suite fails: every 'caught' below would be meaningless"
for label, rel, old, new in MUTANTS:
    f = root / rel
    src = f.read_text()
    assert old in src, f"mutation anchor missing: {label}"
    f.write_text(src.replace(old, new, 1))
    try:
        rc = run()
    finally:
        f.write_text(src)
    print(("caught   " if rc != 0 else "SURVIVED ") + label)
assert run() == 0, "suite fails after restoring all mutants"
print("clean suite passes before and after")
