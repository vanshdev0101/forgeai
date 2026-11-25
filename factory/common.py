"""Shared factory helpers: prompt loading, artifact writing, factory model choice."""
import json
import os
from pathlib import Path
from string import Template

from runtime import llm

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"

# The factory reasons with the larger local model; the agents it builds run on the small one.
FACTORY_MODEL = os.environ.get("FORGE_FACTORY_MODEL", llm.JUDGE_MODEL)


def prompt(_prompt, **values):
    """Load prompts/<_prompt>.md and fill $placeholders. Template ($x) rather than str.format so
    the JSON examples inside prompts don't need brace-escaping. (Underscored parameter so a prompt
    can use $name as a placeholder.)"""
    return Template((PROMPTS / f"{_prompt}.md").read_text()).substitute(
        {k: v if isinstance(v, str) else json.dumps(v, indent=2) for k, v in values.items()})


def ask_json(_prompt, check=None, temperature=0.0, **values):
    """One factory LLM call: fill a prompt, get validated JSON back (with repair retries)."""
    return llm.chat_json([{"role": "user", "content": prompt(_prompt, **values)}],
                         model=FACTORY_MODEL, temperature=temperature, check=check)


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def log(msg):
    print(f"[forge] {msg}", flush=True)
