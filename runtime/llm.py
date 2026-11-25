"""Thin Ollama wrapper: chat, JSON chat with repair, embeddings, token accounting."""
import json
import os
import re

import requests

HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
GEN_MODEL = os.environ.get("FORGE_GEN_MODEL", "qwen3.5-4b-8k")
JUDGE_MODEL = os.environ.get("FORGE_JUDGE_MODEL", "qwen3.5-9b-8k")
EMBED_MODEL = os.environ.get("FORGE_EMBED_MODEL", "nomic-embed-text")

# Running totals for the whole process; the factory snapshots these per stage.
USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}


class LLMError(RuntimeError):
    """Ollama unreachable, timed out, or a model is missing. Message says how to fix it."""


def _post(path, body, timeout):
    try:
        r = requests.post(f"{HOST}{path}", json=body, timeout=timeout)
    except requests.ConnectionError:
        raise LLMError(f"Ollama is not reachable at {HOST}. Start it with `ollama serve`.") from None
    except requests.Timeout:
        raise LLMError(f"Ollama timed out after {timeout}s on {path} (model {body.get('model')}).") from None
    if r.status_code == 404:
        raise LLMError(f"model {body.get('model')!r} is not installed. Run `ollama pull {body.get('model')}`.")
    if not r.ok:
        raise LLMError(f"Ollama {path} returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def preflight(models=None):
    """Fail fast, with a fix-it message, if Ollama is down or a required model is missing."""
    models = models or (GEN_MODEL, EMBED_MODEL)
    try:
        tags = requests.get(f"{HOST}/api/tags", timeout=10).json()
    except (requests.RequestException, ValueError):
        raise LLMError(f"Ollama is not reachable at {HOST}. Start it with `ollama serve`.") from None
    have = {m["name"] for m in tags.get("models", [])}
    have |= {n.removesuffix(":latest") for n in have}
    missing = [m for m in models if m not in have]
    if missing:
        raise LLMError("missing models: " + ", ".join(missing) + ". Run: " +
                       " && ".join(f"ollama pull {m}" for m in missing))


def chat(messages, model=GEN_MODEL, json_mode=False, temperature=0.0, tools=None, timeout=600):
    """One non-streaming chat call. Returns Ollama's `message` dict.

    Defaults to greedy decoding with a fixed seed so eval scores are reproducible: the optimizer
    compares before/after scores, and sampling noise would swamp the effect of a fix. Callers that
    want variety (eval generation, prompt candidates) pass a temperature explicitly."""
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,  # qwen3.5 reasoning traces cost tokens and break JSON
        "options": {"temperature": temperature, "seed": 7},
    }
    if json_mode:
        body["format"] = "json"
    if tools:
        body["tools"] = tools
    data = _post("/api/chat", body, timeout)
    USAGE["calls"] += 1
    USAGE["prompt_tokens"] += data.get("prompt_eval_count", 0)
    USAGE["completion_tokens"] += data.get("eval_count", 0)
    USAGE["seconds"] += data.get("total_duration", 0) / 1e9
    return data["message"]


def parse_json(text):
    """Best-effort JSON extraction: raw, fenced, or first {...} / [...] span."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        start, end = text.find(open_), text.rfind(close)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON found in: {text[:200]!r}")


def chat_json(messages, model=GEN_MODEL, temperature=0.0, retries=2, check=None):
    """Chat in JSON mode; on parse failure or a failed `check(obj) -> error|None`,
    feed the error back and retry. Small models need this more often than you'd hope."""
    msgs = list(messages)
    last_err = None
    for _ in range(retries + 1):
        reply = chat(msgs, model=model, json_mode=True, temperature=temperature)
        content = reply.get("content", "")
        try:
            obj = parse_json(content)
            last_err = check(obj) if check else None
            if not last_err:
                return obj
        except ValueError as e:
            last_err = str(e)
        msgs += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"That output was invalid: {last_err}. "
                                        "Reply again with only the corrected JSON."},
        ]
    raise ValueError(f"chat_json gave up after {retries + 1} tries: {last_err}")


def embed(texts, kind="document", batch=64):
    """Embed a list of strings. nomic-embed-text expects task prefixes."""
    prefix = "search_query: " if kind == "query" else "search_document: "
    out = []
    for i in range(0, len(texts), batch):
        chunk = [prefix + t for t in texts[i:i + batch]]
        out.extend(_post("/api/embed", {"model": EMBED_MODEL, "input": chunk}, 600)["embeddings"])
    return out
