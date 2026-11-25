"""Requirement 1: the intake interviewer.

inventory the documents -> ask the requester at most 5 clarifying questions -> write a structured
requirements document (requirements.json + a readable requirements.md).

Every question carries a default assumption. If nobody answers (an unattended run, or a skipped
question) the default is used and recorded as "assumed", never passed off as the requester's answer.
"""
import csv
from pathlib import Path

from factory.common import ask_json, log
from runtime import rag, schema

MAX_QUESTIONS = 5
EXCERPT_CHARS = 6000


def inventory(docs_dir):
    """Describe every readable document: name, kind, size, CSV columns, LLM summary + topics."""
    docs = rag.load_folder(docs_dir)
    if not docs:
        raise ValueError(f"no readable documents (.md .txt .pdf .csv) in {docs_dir}")
    items = []
    for name, text in docs.items():
        kind = Path(name).suffix.lstrip(".").lower()
        entry = {"name": name, "kind": kind, "words": len(text.split())}
        extra = ""
        if kind == "csv":
            with open(Path(docs_dir) / name, newline="", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                entry.update(columns=header, rows=sum(1 for _ in reader))
            extra = f"CSV with {entry['rows']} rows; columns: {', '.join(header)}\n"
        log(f"inventory: summarising {name}")
        out = ask_json("intake_summarize", check=_check_summary, name=name, kind=kind, extra=extra,
                       excerpt=text[:EXCERPT_CHARS])
        entry.update(summary=out["summary"].strip(), topics=[str(t) for t in out["topics"]][:10])
        items.append(entry)
    return items


def _check_summary(o):
    if not isinstance(o, dict) or not isinstance(o.get("summary"), str) or not isinstance(o.get("topics"), list):
        return 'need {"summary": str, "topics": [str, ...]}'
    return None


def inventory_text(inv):
    lines = []
    for d in inv:
        cols = f"; columns: {', '.join(d['columns'])}; {d['rows']} rows" if d["kind"] == "csv" else ""
        lines.append(f"- {d['name']} ({d['kind']}, {d['words']} words{cols}): {d['summary']} "
                     f"Topics: {', '.join(d['topics'])}.")
    return "\n".join(lines)


def questions(brief, inv):
    """At most MAX_QUESTIONS clarifying questions, each with a default assumption. The cap is
    enforced here, not trusted to the model."""
    def check(o):
        qs = o.get("questions") if isinstance(o, dict) else None
        if not isinstance(qs, list):
            return 'need {"questions": [...]}'
        for q in qs:
            if not isinstance(q, dict) or not q.get("question") or not q.get("default_assumption"):
                return "every question needs non-empty 'question' and 'default_assumption'"
        return None
    out = ask_json("intake_questions", check=check, brief=brief, inventory=inventory_text(inv),
                   max_questions=str(MAX_QUESTIONS))
    seen, qs = set(), []
    for q in out["questions"]:
        key = q["question"].strip().lower()
        if key not in seen:
            seen.add(key)
            qs.append({"question": q["question"].strip(), "why": str(q.get("why", "")).strip(),
                       "default_assumption": q["default_assumption"].strip()})
    if len(qs) > MAX_QUESTIONS:
        log(f"model proposed {len(qs)} questions; keeping the first {MAX_QUESTIONS}")
    return qs[:MAX_QUESTIONS]


def interview(qs, answer_fn):
    """Put each question to the requester via answer_fn(question_dict) -> str | None."""
    out = []
    for q in qs:
        ans = answer_fn(q)
        ans = ans.strip() if isinstance(ans, str) else ""
        out.append({"question": q["question"], "answer": ans or q["default_assumption"],
                    "source": "requester" if ans else "assumed"})
    return out


def cli_answerer(q):
    print(f"\nQ: {q['question']}\n   (if you skip: {q['default_assumption']})")
    try:
        return input("A: ")
    except EOFError:
        return None


def file_answerer(answers):
    """Answers from a JSON list (by position) or dict (by exact question text)."""
    state = {"i": 0}

    def answer(q):
        if isinstance(answers, dict):
            return answers.get(q["question"])
        i = state["i"]
        state["i"] += 1
        return answers[i] if i < len(answers) else None
    return answer


def requirements(brief, inv, clarifications):
    """Build and validate the requirements document."""
    names = {d["name"] for d in inv}
    req_schema = schema.load("requirements")

    def check(o):
        errs = schema.errors(o, req_schema) if isinstance(o, dict) else ["not an object"]
        if not errs and not o["must_answer_topics"]:
            errs.append("must_answer_topics is empty")
        return "; ".join(errs[:6]) or None

    req = ask_json("intake_requirements", check=check, brief=brief, inventory=inventory_text(inv),
                   clarifications=clarifications)
    # Deterministic clean-up of what a small model gets wrong: unknown document names.
    for t in req["must_answer_topics"]:
        bad = [s for s in t["source_docs"] if s not in names]
        t["source_docs"] = [s for s in t["source_docs"] if s in names]
        if bad:
            req["assumptions"].append(f"dropped unknown source documents {bad} from topic '{t['topic']}'")
    req["clarifications"] = clarifications
    req["documents"] = [{k: d[k] for k in ("name", "kind", "summary")} for d in inv]
    req["brief"] = brief
    return req


def render_markdown(req):
    """Human-readable requirements document."""
    lines = [f"# Requirements: {req['name']}", "", req["summary"], "",
             f"- **Audience:** {req['audience']}", f"- **Tone:** {req['tone']}",
             f"- **Answer length:** {req['answer_length']}", "", "## Brief", "", f"> {req['brief']}", "",
             "## Must answer", "", "| Topic | Covers | Source documents |", "|---|---|---|"]
    for t in req["must_answer_topics"]:
        lines.append(f"| {t['topic']} | {t['details']} | {', '.join(t['source_docs']) or '**none**'} |")
    lines += ["", "## Must refuse", ""]
    lines += [f"- **{t['topic']}**: {t['reason']}" for t in req["must_refuse_topics"]]
    if req.get("groundability"):
        g = req["groundability"]
        lines += ["", "## Groundability", "", g.get("summary", "")]
        for f in g.get("flags", []):
            lines.append(f"- **{f['topic']}**: {f['verdict']}, {f['evidence']}")
    lines += ["", "## Clarifications", ""]
    for c in req.get("clarifications", []):
        lines.append(f"- **Q:** {c['question']}  \n  **A ({c['source']}):** {c['answer']}")
    lines += ["", "## Assumptions", ""] + [f"- {a}" for a in req["assumptions"]]
    lines += ["", "## Documents", ""] + [f"- `{d['name']}` ({d['kind']}): {d['summary']}" for d in req["documents"]]
    return "\n".join(lines) + "\n"
