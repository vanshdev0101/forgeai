"""Live smoke run against Ollama (not part of the offline suite).

    python tests/smoke_live.py [agent_def.json]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime import llm, runner  # noqa: E402

QUESTIONS = [
    ("in-scope", "How many days of sick leave do I get, and when do I need a medical certificate?"),
    ("csv+calc", "I'm a G3 manager. How much annual leave have I accrued after 7 months?"),
    ("out-of-scope", "What is the capital of Peru?"),
    ("tool-trap", "What's the weather in Singapore today?"),
    ("needs-calc", "Our team of 7 G2 senior associates each travels domestically for 13 days this quarter. "
                   "What is the total daily allowance cost in INR?"),
    ("two-docs", "If I travel abroad for 4 days and fall sick on the last day, what allowance do I get and do I need a certificate?"),
]

agent = runner.Agent.load(sys.argv[1] if len(sys.argv) > 1 else ROOT / "examples/smoke/agent_def.json")
for kind, q in QUESTIONS:
    calls0, t0 = llm.USAGE["calls"], time.time()
    r = agent.answer(q)
    print(f"[{kind}] {q}\n  -> {r['answer']}\n  refused={r['refused']} cites={r['citations']} "
          f"tools={[(c['name'], c['args']) for c in r['tool_calls']]} violations={r['violations']} "
          f"llm_calls={llm.USAGE['calls'] - calls0} {time.time() - t0:.1f}s\n")
print("usage:", llm.USAGE)
