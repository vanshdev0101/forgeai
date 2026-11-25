"""Requirement 3: the agent generator.

requirements + documents -> a complete declarative agent definition:
  - system prompt: LLM-written persona + a deterministic scope / must-refuse block
  - retrieval parameters, with min_score calibrated on this corpus
  - tools: attached only when the requirements need one AND the supported documents make it usable
  - output contract
"""
import os
import re
import statistics
from pathlib import Path

from factory.common import FACTORY_MODEL, ask_json, log
from runtime import llm, rag, schema, tools

DEFAULT_RETRIEVAL = {"chunk_words": 250, "overlap": 40, "k": 4}
ANSWER_WORDS = {"short": 80, "medium": 150, "detailed": 250}

# Questions no document-grounded assistant should match. Used to measure how high an
# irrelevant question scores against THIS corpus (nomic-embed-text compresses scores, so a
# fixed threshold that works on one corpus refuses real questions on another).
OFF_TOPIC_PROBES = [
    "What is the capital of Peru?",
    "Give me a recipe for butter chicken.",
    "Who won the 2022 football World Cup?",
    "How do I write quicksort in Python?",
    "Explain how photosynthesis works.",
    "Summarise the plot of Hamlet.",
    "How do I change a flat tyre on a bicycle?",
    "What is the distance from the Earth to the Moon?",
    "What are the rules of chess castling?",
    "Translate 'good morning' into French.",
    "Which guitar chords are in the key of G major?",
    "What is the best smartphone to buy this year?",
]
MARGIN = 0.02

# Tool selection is evidence-based. Four rounds of letting the factory model decide (propose,
# repair, justify with an example, independent audit) oscillated between attaching tools "just in
# case" and rejecting needed ones. Each tool instead has two generic tests:
#   NEED: does the brief / requirements / clarifications call for what the tool does?
#   FEASIBLE: do the passages retrieved for SUPPORTED topics contain what the tool works on?
# Attach only when both hold. Rules are per tool capability, never per brief.
WEATHER_WORDS = re.compile(r"\b(weather|forecast|temperature|wind speed|winds?|rain\w*|storms?|sea state|"
                           r"sea conditions|weather conditions|port conditions|monsoon)\b", re.I)
NEED = {
    "calculator": re.compile(r"\b(totals?|costs?|prices?|pricing|how much|how many|calculat\w*|allowances?|"
                             r"accru\w*|pro-?rat\w*|percent\w*|budget\w*|quantit\w*|rates?|sum|amounts?|"
                             r"multiply|arithmetic)\b", re.I),
    "current_date": re.compile(r"\b(deadlines?|within \w+ (working |calendar )?(days?|hours?|weeks?|months?)|"
                               r"eligib\w*|expir\w*|lead[- ]times?|overdue|days left|how long|in advance|"
                               r"due dates?|time limits?|application windows?|today)\b", re.I),
    "weather": WEATHER_WORDS,
}
FEASIBLE = {
    # (?<![a-z])...(?![a-z]) instead of \b so CSV column names like monthly_accrual_days count.
    "calculator": re.compile(r"((INR|USD|EUR|GBP|Rs\.?|\$|€|£)\s?\d|\d\s?%|\bper (day|month|year|hour|unit|"
                             r"piece|item|night|week|kg|litre)\b|(?<![a-z])(monthly|daily|unit[_ ]price|price|"
                             r"cost|rate)(?![a-z]))", re.I),
    "current_date": re.compile(r"\b(within \d+|\d+ (working |calendar |business )?(days?|weeks?|months?) "
                               r"(in advance|before|after|from)|deadline|expir\w*|valid (until|for)|"
                               r"lead time)", re.I),
}
# What a document-free tool can answer on its own, for topics no document covers.
TOOL_PROVIDES = {
    "weather": WEATHER_WORDS,
    "current_date": re.compile(r"\b(today|today's|current date|day of the week|what day)\b", re.I),
}
NEVER = re.compile(r"(?!x)x")


def tool_served_topics(req, chosen):
    """Undocumented topics an attached document-free tool answers directly."""
    return [t["topic"] for t in req["must_answer_topics"] if not t["source_docs"]
            and any(TOOL_PROVIDES.get(n, NEVER).search(f"{t['topic']} {t['details']}") for n in chosen)]


def _top(index, q):
    hits = index.search(q, k=1)
    return hits[0]["score"] if hits else 0.0


def off_topic_scores(index):
    """How well each irrelevant probe matches this corpus. max() + MARGIN is the 'off-topic
    ceiling' that both the groundability guard and calibration use."""
    return {q: _top(index, q) for q in OFF_TOPIC_PROBES}


def calibrate(index, req, off=None):
    """Choose min_score from measurements on THIS corpus.

    In-scope side: the user-style sample questions the groundability guard wrote for supported
    topics (topic labels are keyword-dense and score ~0.1 higher than real questions, so they
    overstate separation; they are only the fallback). Off-topic side: the fixed probes.
      separable -> just above the off-topic ceiling: the gate can refuse off-topic on its own.
      overlap   -> just below the weakest real question: the gate is only a recall floor, and the
                   agent's scope rules do the refusing. Refusing real questions is the worse error.
    """
    off = off or off_topic_scores(index)
    on, source = {}, "sample_questions"
    for t in req["must_answer_topics"]:
        if t["source_docs"]:
            for q in t.get("sample_questions") or []:
                on[q] = _top(index, q)
    if not on:
        source = "topic_labels"
        on = {t["topic"]: _top(index, f"{t['topic']}: {t['details']}")
              for t in req["must_answer_topics"] if t["source_docs"]}
    off_max = max(off.values())
    on_min = min(on.values()) if on else None
    separable = on_min is None or on_min > off_max + 2 * MARGIN
    # ponytail: on overlap, 2-3 sample questions overstate the in-scope floor (live: samples 0.61,
    # real questions 0.54), so also cap at the probe median; Phase 4 retunes from eval failures.
    threshold = off_max + MARGIN if separable else max(0.0, min(on_min - MARGIN, statistics.median(off.values())))
    return round(threshold, 3), {
        "off_topic_max": round(off_max, 4), "in_scope_min": None if on_min is None else round(on_min, 4),
        "in_scope_source": source, "separable": separable,
        "gate_role": "refuses off-topic on its own" if separable else
                     "recall floor only; the agent's scope rules refuse off-topic questions",
        "off_topic_scores": off, "in_scope_scores": on,
    }


def _need_text(req):
    """What the requester asked for: brief, summary, every topic, and the clarification answers."""
    parts = [req.get("brief", ""), req["summary"]]
    parts += [f"{t['topic']} {t['details']}" for t in req["must_answer_topics"]]
    parts += [c.get("answer", "") for c in req.get("clarifications", [])]
    return " ".join(parts)


def _first(rx, text):
    m = rx.search(text)
    return m.group(0) if m else None


def select_tools(req, inv, index, ceiling):
    """Evidence-based tool selection. Returns (tool names, rationale map, decision log).
    Evidence comes only from passages retrieved for topics the guard verified as supported,
    so an undocumented topic can never justify a corpus-bound tool."""
    need_text = _need_text(req)
    grounded = [t for t in req["must_answer_topics"] if t["source_docs"]]
    passages = {}
    for t in grounded:
        for h in index.search(f"{t['topic']}: {t['details']}", k=4, min_score=ceiling):
            passages[h["id"]] = h
    csv_docs = sorted({d for t in grounded for d in t["source_docs"] if d.lower().endswith(".csv")})
    csv_files = {d["name"] for d in inv if d["kind"] == "csv"}

    def evidence(rx):
        for h in passages.values():
            m = rx.search(h["text"])
            if m:
                return f"{h['id']}: ...{h['text'][max(0, m.start() - 40):m.end() + 40]}..."
        return None

    decisions = []
    for name in tools.REGISTRY:
        need, feas = None, None
        if name == "csv_lookup":
            need = f"supported topics sourced from {csv_docs}" if csv_docs else None
            feas = "CSV present in the document folder" if csv_docs and set(csv_docs) <= csv_files else None
        elif name == "weather":
            # Live API: no document evidence needed, but the requester must actually ask for it.
            need = _first(WEATHER_WORDS, need_text)
            feas = "live open-meteo API" if need else None
        else:
            need, feas = _first(NEED[name], need_text), evidence(FEASIBLE[name])
        served = [t["topic"] for t in req["must_answer_topics"] if not t["source_docs"]
                  and TOOL_PROVIDES.get(name, NEVER).search(f"{t['topic']} {t['details']}")]
        attach = bool(need and feas) or bool(served)
        if attach:
            reason = (f"answers undocumented topic(s) {served} directly" if served and not (need and feas)
                      else f"needed ({need!r} in the requirements) and usable ({feas})")
        elif not need:
            reason = "the brief and requirements never call for it"
        else:
            reason = f"asked for ({need!r}) but no supported topic's passages give it anything to work on"
        decisions.append({"tool": name, "attached": attach, "need_signal": need, "evidence": feas,
                          "serves_undocumented_topics": served, "reason": reason})
    chosen = [d["tool"] for d in decisions if d["attached"]]
    return chosen, {d["tool"]: d["reason"] for d in decisions if d["attached"]}, decisions


def system_prompt(req, persona, tool_topics=()):
    """Persona from the model + scope and refusal rules from the requirements, verbatim, so no
    topic can be silently dropped by the model. `tool_topics` are undocumented topics a tool answers."""
    covered = [t for t in req["must_answer_topics"] if t["source_docs"] or t["topic"] in tool_topics]
    uncovered = [t for t in req["must_answer_topics"] if not t["source_docs"] and t["topic"] not in tool_topics]
    parts = [persona.strip(), "", "## Scope", "You answer questions about:"]
    parts += [f"- {t['topic']}: {t['details']}" for t in covered]
    if uncovered:
        parts += ["", "Your documents do not cover the following yet. If asked, say so and refuse rather than guess:"]
        parts += [f"- {t['topic']}" for t in uncovered]
    parts += ["", "## Must refuse", "Decline, using the refusal message, any question about:"]
    parts += [f"- {t['topic']} ({t['reason']})" for t in req["must_refuse_topics"]]
    parts += ["- anything unrelated to the scope above"]
    return "\n".join(parts)


def _req_view(req):
    return {k: req[k] for k in ("summary", "audience", "tone", "answer_length", "must_answer_topics",
                                "must_refuse_topics")}


def build_index(docs_dir):
    r = DEFAULT_RETRIEVAL
    return rag.Index.from_folder(docs_dir, r["chunk_words"], r["overlap"])


def generate(req, inv, docs_dir, out_dir, index=None, off=None):
    """Produce, validate and return the agent definition (also proves the runner can load it)."""
    from runtime.runner import Agent

    log("generator: writing persona + refusal message")
    def check(o):
        if not isinstance(o, dict) or not all(isinstance(o.get(k), str) and o[k].strip()
                                              for k in ("persona", "refusal_message", "description")):
            return "need non-empty persona, refusal_message and description strings"
        return None
    voice = ask_json("gen_system_prompt", check=check, requirements=_req_view(req))

    index = index or build_index(docs_dir)
    off = off or off_topic_scores(index)

    log("generator: selecting tools from evidence")
    chosen, rationale, tool_log = select_tools(req, inv, index, max(off.values()) + MARGIN)

    log("generator: calibrating retrieval threshold")
    r = dict(DEFAULT_RETRIEVAL)
    r["min_score"], calibration = calibrate(index, req, off)

    definition = {
        "name": re.sub(r"[^a-z0-9-]+", "-", req["name"].lower()).strip("-") or "agent",
        "description": voice["description"].strip(),
        "system_prompt": system_prompt(req, voice["persona"], tool_served_topics(req, chosen)),
        "docs_dir": os.path.relpath(Path(docs_dir).resolve(), Path(out_dir).resolve()),
        "retrieval": r,
        "tools": chosen,
        "tool_rationale": rationale,
        "output_contract": {"must_cite": True, "refusal_message": voice["refusal_message"].strip(),
                            "max_words": ANSWER_WORDS.get(req["answer_length"], 150)},
        "provenance": {"factory_model": FACTORY_MODEL, "agent_model": llm.GEN_MODEL,
                       "embed_model": llm.EMBED_MODEL, "iteration": 0,
                       "calibration": calibration, "tool_decisions": tool_log},
    }
    errs = schema.errors(definition, schema.load("agent_def"))
    if errs:
        raise ValueError("generator produced an invalid definition: " + "; ".join(errs))
    Agent(definition, base_dir=out_dir, index=index)  # must load in the generic runner
    return definition
