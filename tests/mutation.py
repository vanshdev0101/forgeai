"""Tiny mutation-testing harness shared by tests/mutate_phase*.py.

Each mutant replaces one guard in the source; the named test file must then fail. A surviving mutant
means a test that would not notice that guard breaking. Guarantees:
  - the clean suite must pass before and after, otherwise every "caught" is meaningless;
  - PYTHONDONTWRITEBYTECODE=1: a same-size mutation restored within the same second once left stale
    bytecode running, silently corrupting later results.
"""
import os
import subprocess
import sys
from pathlib import Path

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def run_suite(test_file, mutants, root=None):
    root = Path(root or Path(__file__).resolve().parent.parent)

    def run():
        try:
            return subprocess.run([sys.executable, test_file], cwd=root, capture_output=True,
                                  timeout=300, env=ENV).returncode
        except subprocess.TimeoutExpired:
            return "timeout"

    assert run() == 0, f"clean {test_file} fails: every 'caught' would be meaningless"
    survived = 0
    for label, rel, old, new in mutants:
        f = root / rel
        src = f.read_text()
        assert old in src, f"mutation anchor missing: {label}"
        f.write_text(src.replace(old, new, 1))
        try:
            rc = run()
        finally:
            f.write_text(src)
        survived += rc == 0
        print(("caught   " if rc != 0 else "SURVIVED ") + label)
    assert run() == 0, f"{test_file} fails after restoring all mutants"
    print(f"\n{len(mutants) - survived}/{len(mutants)} caught; clean suite passes before and after")
    return survived
