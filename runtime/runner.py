"""Generic chat runner: loads ANY agent definition and answers questions under its contract.

    python -m runtime.runner path/to/agent_def.json             # interactive
    python -m runtime.runner path/to/agent_def.json --ask "..."  # one question, prints JSON

Nothing agent-specific lives here: the definition supplies the prompt, retrieval
parameters, tools and output contract. The runner enforces the contract and reports
violations instead of hiding them, so the judge can see them.
"""
import argparse
import copy
import csv
import json
import sys
from pathlib import Path

from runtime import llm, rag, schema, tools

MAX_TOOL_ROUNDS = 3
CONTEXT_FREE_TOOLS = {"current_date", "weather"}  # tools that can answer with zero retrieved passages

CONTRACT = """
## How to answer (mandatory)
- Use ONLY the numbered context passages{tool_clause}. Do not use outside knowledge.{tool_rule}
- If the context does not contain the answer, or the question is outside your scope, refuse: set "refused" to true and "answer" to exactly: {refusal!r}
- {cite_rule}
- Keep the answer under {max_words} words.
- Reply with a single JSON object and nothing else:
  {{"answer": "<text>", "citations": ["S1", ...], "refused": true|false{need_tool_field}}}
""".strip()


class Agent:
    def __init__(self, definition, base_dir=".", index=None):
        errs = schema.errors(definition, schema.load("agent_def"))
        if errs:
            raise ValueError("invalid agent definition:\n  " + "\n  ".join(errs))
        self.d = definition
        docs = Path(definition["docs_dir"])
        self.docs_dir = docs if docs.is_absolute() else (Path(base_dir) / docs).resolve()
        r = definition["retrieval"]
        self.index = index or rag.Index.from_folder(self.docs_dir, r["chunk_words"], r["overlap"])
        self.tool_names = list(definition["tools"])
        self.tool_schemas = [self._schema_for(t) for t in self.tool_names]

    def _schema_for(self, name):
        """Registry schema, with csv_lookup told which files/columns actually exist, so a
        small model stops inventing `catalogue.csv`."""
        s = copy.deepcopy(tools.REGISTRY[name]["schema"])
        if name == "csv_lookup":
            files = []
            for p in sorted(self.docs_dir.glob("*.csv")):
                with open(p, newline="", errors="replace") as f:
                    header = next(csv.reader(f), [])
                files.append(f"{p.name} (columns: {', '.join(header)})")
            s["function"]["description"] += " Available files: " + ("; ".join(files) or "none") + "."
        return s

    @classmethod
    def load(cls, path, index=None):
        path = Path(path)
        return cls(json.loads(path.read_text()), base_dir=path.parent, index=index)

    def system_message(self):
        oc = self.d["output_contract"]
        tool_clause = " and the results of the tools you call" if self.tool_names else ""
        cite_rule = ('Every non-refusal answer MUST list the tags of the passages it relies on in "citations", '
                     'e.g. ["S1", "S3"] (answers based only on tool results may cite nothing).' if oc["must_cite"]
                     else 'List supporting passage tags (e.g. "S1") in "citations" when there are any.')
        return self.d["system_prompt"].strip() + "\n\n" + CONTRACT.format(
            tool_clause=tool_clause, tool_rule=self._tool_menu(),
            need_tool_field=', "need_tool": null|"<tool name>"' if self.tool_names else "",
            refusal=oc["refusal_message"],
            cite_rule=cite_rule, max_words=oc.get("max_words", 150))

    def _tool_menu(self):
        if not self.tool_names:
            return ""
        lines = "\n".join(f"    - {t}: use when {tools.REGISTRY[t]['use_when']}" for t in self.tool_names)
        return ('\n- Your JSON also has a "need_tool" field. Leave it null for most questions. Set it to a tool '
                "name (and leave answer empty) when the answer needs a step you must not do in your head: any "
                "multiplication or percentage on numbers from the passages, an exact table lookup, or today's date. "
                'Example: "17 people x 23 days x INR 2,500 plus 18.5%" -> {"answer": "", "citations": [], '
                '"refused": false, "need_tool": "calculator"}. Never request a tool for a question outside your '
                "scope - refuse instead. Tools:\n" + lines)

    def _json_reply(self, msgs, trace, record_failure):
        """One JSON-mode turn with a single repair attempt. Returns a dict (possibly a fallback)."""
        reply = llm.chat(msgs, json_mode=True)
        try:
            out = llm.parse_json(reply.get("content", ""))
            if isinstance(out, dict) and ("answer" in out or "need_tool" in out):
                return out
        except ValueError:
            pass
        if record_failure:
            trace["violations"].append("bad_json")
        repair = msgs + [reply, {"role": "user", "content": 'Reply again with only the required JSON object: '
                                                            '{"answer": ..., "citations": [...], "refused": ...}'}]
        try:
            return llm.chat_json(repair, retries=1, check=lambda o: None if isinstance(o, dict) and "answer" in o
                                 else "need an object with an 'answer' key")
        except ValueError:
            return {"answer": reply.get("content", ""), "citations": [], "refused": False}

    def _tool_loop(self, msgs, tool, trace):
        """Let the model call tools (free-text turns: JSON mode suppresses tool calls on small
        models), then finalize to JSON. Identical calls run once; the last round withholds tools."""
        msgs.append({"role": "user", "content": f"Call {tool} now with the arguments you need." if tool in
                     self.tool_names else "Call the tool you need now."})
        reply = llm.chat(msgs, tools=self.tool_schemas)
        seen = {}
        for rnd in range(MAX_TOOL_ROUNDS):
            calls = reply.get("tool_calls") or []
            if not calls:
                break
            msgs.append(reply)
            for c in calls:
                name, args = c["function"]["name"], c["function"].get("arguments") or {}
                key = (name, json.dumps(args, sort_keys=True))
                if key in seen:  # small models re-issue identical calls; don't pay for them twice
                    result = {"note": "already called with these arguments; use the earlier result", **seen[key]}
                else:
                    result = seen[key] = tools.call(name, args, self.tool_names, self.docs_dir)
                    trace["tool_calls"].append({"name": name, "args": args, "result": result})
                msgs.append({"role": "tool", "tool_name": name, "content": json.dumps(result, default=str)})
            last = rnd == MAX_TOOL_ROUNDS - 1
            if last:
                msgs.append({"role": "user", "content": "Tool budget used up. Answer now from what you have."})
            reply = llm.chat(msgs, tools=None if last else self.tool_schemas)
        msgs += [reply, {"role": "user", "content": "Now give your final answer as the required JSON object."}]
        out = self._json_reply(msgs, trace, record_failure=True)
        out.pop("need_tool", None)
        return out

    def answer(self, question):
        """Answer one question. Returns a trace dict the judge can score."""
        r, oc = self.d["retrieval"], self.d["output_contract"]
        hits = self.index.search(question, k=r["k"], min_score=r["min_score"])
        trace = {"question": question, "retrieved": [{"id": h["id"], "score": h["score"]} for h in hits],
                 "tool_calls": [], "violations": []}

        # Deterministic refusal: nothing relevant retrieved and no tool that works without the
        # documents. Saves the calls and removes the model's chance to hallucinate over nothing.
        if not hits and not set(self.tool_names) & CONTEXT_FREE_TOOLS:
            return {**trace, "answer": oc["refusal_message"], "citations": [], "refused": True,
                    "refusal_source": "no_context"}

        # Short source tags: a 4b model copies "S2" reliably, "leave_policy.md#0" much less so.
        tags = {f"S{i}": h["id"] for i, h in enumerate(hits, 1)}
        context = "\n\n".join(f"[S{i}] (from {h['doc']})\n{h['text']}" for i, h in enumerate(hits, 1)) \
            or "(no relevant passages found)"
        msgs = [{"role": "system", "content": self.system_message()},
                {"role": "user", "content": f"Context passages:\n\n{context}\n\nQuestion: {question}"}]
        # Stage 1: answer in JSON with no tools offered. Tools are opt-in via {"need_tool": ...};
        # offering them up front makes a 4b model call them gratuitously and blend in junk.
        out = self._json_reply(msgs, trace, record_failure=True)
        if out.get("need_tool") and self.tool_names:
            msgs.append({"role": "assistant", "content": json.dumps(out)})
            out = self._tool_loop(msgs, out["need_tool"], trace)
        out.pop("need_tool", None)
        tool_backed = any("error" not in (t["result"] or {}) for t in trace["tool_calls"])
        result = self._enforce(out, tags, tool_backed)
        trace["violations"] += result.pop("violations")
        return {**trace, **result}

    def _enforce(self, out, tags, tool_backed=False):
        """Check the model's reply against the contract; record (not hide) every violation.
        `tags` maps the S-tags shown to the model to real chunk ids."""
        oc = self.d["output_contract"]
        answer = str(out.get("answer", "")).strip()
        refused = bool(out.get("refused")) or answer == oc["refusal_message"]
        valid_ids = set(tags.values())
        cited = [str(c).strip("[] ") for c in (out.get("citations") or []) if isinstance(c, (str, int))]
        good = []
        for c in cited:
            cid = tags.get(c) or tags.get(f"S{c}") or (c if c in valid_ids else None)
            if cid and cid not in good:
                good.append(cid)
        violations = []
        if len(good) < len(set(cited)):
            violations.append("invalid_citation")
        if refused and answer != oc["refusal_message"]:
            violations.append("nonstandard_refusal")
        if oc["must_cite"] and not refused and not good and not tool_backed:
            violations.append("uncited_answer")
        max_words = oc.get("max_words", 150)
        if len(answer.split()) > max_words * 1.5:
            violations.append("too_long")
        return {"answer": answer, "citations": good, "refused": refused, "refusal_source": "model" if refused else None,
                "violations": violations}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chat with a ForgeAI agent definition.")
    ap.add_argument("definition")
    ap.add_argument("--ask", help="answer one question and print the trace as JSON")
    ap.add_argument("--debug", action="store_true", help="interactive mode: show retrieval and tool calls")
    a = ap.parse_args(argv)
    agent = Agent.load(a.definition)

    if a.ask:
        res = agent.answer(a.ask)
        print(json.dumps(res, indent=2, default=str))
        return

    print(f"{agent.d['name']}: {agent.d['description']}\n(tools: {', '.join(agent.tool_names) or 'none'}; "
          f"{len(agent.index.chunks)} chunks; Ctrl-D to quit)\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            continue
        res = agent.answer(q)
        print(f"\nagent> {res['answer']}")
        if res["citations"]:
            print(f"  sources: {', '.join(res['citations'])}")
        if res["violations"]:
            print(f"  contract violations: {', '.join(res['violations'])}")
        if a.debug:
            print(f"  retrieved: {res['retrieved']}")
            for t in res["tool_calls"]:
                print(f"  tool {t['name']}({t['args']}) -> {json.dumps(t['result'], default=str)[:200]}")
        print()


if __name__ == "__main__":
    sys.exit(main())
