"""Mutation check for the Phase 1 suite: break each guard in turn; tests/test_phase1.py must fail every time.

    python tests/mutate_phase1.py
"""
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
MUTANTS = [
    ("tool gate removed", "runtime/tools.py",
     "if name not in allowed or name not in REGISTRY:", "if name not in REGISTRY:"),
    ("citation filter removed", "runtime/runner.py",
     "if len(good) < len(set(cited)):", "if False:"),
    ("csv path confinement removed", "runtime/tools.py",
     "if path.parent != Path(docs_dir).resolve() or path.suffix.lower() != \".csv\":", "if False:"),
    ("deterministic refusal removed", "runtime/runner.py",
     "if not hits and not set(self.tool_names) & CONTEXT_FREE_TOOLS:", "if False:"),
    ("refusal ignores context-free tools", "runtime/runner.py",
     "if not hits and not set(self.tool_names) & CONTEXT_FREE_TOOLS:", "if not hits:"),
    ("tag mapping removed", "runtime/runner.py",
     "cid = tags.get(c) or tags.get(f\"S{c}\") or (c if c in valid_ids else None)",
     "cid = c if c in valid_ids else None"),
    ("dedupe removed", "runtime/runner.py", "if key in seen:", "if False:"),
    ("last round keeps tools", "runtime/runner.py",
     "reply = llm.chat(msgs, tools=None if last else self.tool_schemas)",
     "reply = llm.chat(msgs, tools=self.tool_schemas)"),
    ("stage 1 offers tools", "runtime/runner.py",
     "reply = llm.chat(msgs, json_mode=True)", "reply = llm.chat(msgs, json_mode=True, tools=self.tool_schemas or None)"),
    ("tool-backed exemption removed", "runtime/runner.py",
     "and not good and not tool_backed:", "and not good:"),
    ("csv file injection removed", "runtime/runner.py",
     "s[\"function\"][\"description\"] += ", "_ = "),
    ("furniture filter removed", "runtime/rag.py",
     "if norm(l) not in furniture)", "if True)"),
    ("furniture ignores length", "runtime/rag.py",
     "and len(n.split()) <= max_words}", "}"),
    ("connection error not wrapped", "runtime/llm.py",
     "except requests.ConnectionError:\n        raise LLMError", "except KeyError:\n        raise LLMError"),
    ("preflight skips model check", "runtime/llm.py", "if missing:", "if False:"),
    ("cli catch removed", "runtime/runner.py",
     "except (llm.LLMError, ValueError, FileNotFoundError) as e:", "except ZeroDivisionError as e:"),
    ("empty answer shown", "runtime/runner.py",
     "        if empty:  # never show a blank reply", "        if False:  # never show a blank reply"),
    ("exact code match removed", "runtime/rag.py", "for code in dict.fromkeys(CODE.findall(query)):",
     "for code in []:"),
    ("exact match allows partial codes", "runtime/rag.py",
     'rx = re.compile(rf"(?<![\\w-]){re.escape(code)}(?![\\w-])", re.I)',
     'rx = re.compile(re.escape(code), re.I)'),
    ("pow guard removed", "runtime/tools.py", "abs(right) > 100", "abs(right) > 10**9"),
]
import os  # noqa: E402
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # stale .pyc made restored mutants linger


def run():
    try:
        return subprocess.run([sys.executable, "tests/test_phase1.py"], cwd=root,
                              capture_output=True, timeout=60, env=ENV).returncode
    except subprocess.TimeoutExpired:
        return "timeout"


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
    print(("caught   " if rc != 0 else "SURVIVED ") + label + f"  (rc={rc})")
assert run() == 0, "suite fails after restoring all mutants"
print("clean suite passes before and after")
