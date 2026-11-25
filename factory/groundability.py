"""Requirement 2: the groundability guard.

Before an agent is generated, check every must-answer topic against the documents themselves. The
requirements step's own claims ("source_docs") are not trusted: in a live run the factory model claimed
a salary figure was in a document that contains none.

Per topic:
  1. retrieval gate (no LLM): best passage scoring under the off-topic ceiling -> unsupported
  2. the factory model reads the retrieved passages and gives a verdict plus a verbatim quote
  3. code verifies the quote is really in the passages; a claimed support with a quote that is
     not there is downgraded to unsupported
The verified result replaces source_docs; unsupported topics are refused by the generated agent.
"""
import re

from factory.common import ask_json, log

K = 3
QUOTE_MATCH = 0.7  # share of the quote's content words that must appear in the passages
VERDICTS = ("supported", "partial", "unsupported")


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]


def quote_found(quote, passages):
    """True if most of the quote's content words occur in the passages (tolerates small
    paraphrases and whitespace/punctuation drift from pdftotext)."""
    q = _words(quote)
    if len(q) < 3:
        return False
    hay = set(_words(" ".join(passages)))
    return sum(w in hay for w in q) / len(q) >= QUOTE_MATCH


def check_topic(index, topic, ceiling):
    query = f"{topic['topic']}: {topic['details']}"
    hits = index.search(query, k=K)
    best = hits[0]["score"] if hits else 0.0
    base = {"topic": topic["topic"], "best_score": round(best, 4), "claimed_docs": topic["source_docs"]}
    if best < ceiling:
        return {**base, "verdict": "unsupported", "docs": [], "method": "retrieval_gate", "sample_questions": [],
                "evidence": f"best passage scores {best:.3f}, below the off-topic ceiling {ceiling:.3f}"}

    passages = "\n\n".join(f"[{h['id']}]\n{h['text']}" for h in hits)

    def check(o):
        if not isinstance(o, dict) or o.get("verdict") not in VERDICTS:
            return f'need {{"verdict": one of {list(VERDICTS)}, "quote": ..., "missing": ...}}'
        return None
    out = ask_json("ground_check", check=check, topic=topic["topic"], details=topic["details"], passages=passages)
    verdict, quote = out["verdict"], str(out.get("quote") or "")
    method = "llm_verified"
    if verdict != "unsupported" and not quote_found(quote, [h["text"] for h in hits]):
        verdict, method = "unsupported", "quote_not_in_passages"
    if verdict == "unsupported":
        evidence = (f"model quoted {quote[:120]!r}, which is not in the passages" if method == "quote_not_in_passages"
                    else str(out.get("missing") or "passages do not contain the needed facts"))
        docs = []
    else:
        evidence = f"quote: {quote[:160]!r}" + (f"; missing: {out['missing']}" if out.get("missing") else "")
        docs = sorted({h["doc"] for h in hits if h["score"] >= ceiling})
    samples = [str(q).strip() for q in (out.get("sample_questions") or []) if str(q).strip()][:2] if docs else []
    return {**base, "verdict": verdict, "docs": docs, "method": method, "evidence": evidence,
            "sample_questions": samples}


def guard(req, index, ceiling):
    """Check every must-answer topic; rewrite source_docs from evidence; attach a report."""
    flags = []
    for t in req["must_answer_topics"]:
        log(f"groundability: {t['topic']}")
        r = check_topic(index, t, ceiling)
        t["source_docs"] = r["docs"]
        t["groundability"] = r["verdict"]
        t["sample_questions"] = r["sample_questions"]  # user-style questions; calibration measures these
        flags.append(r)
    unsupported = [f["topic"] for f in flags if f["verdict"] == "unsupported"]
    contradicted = [f["topic"] for f in flags if f["verdict"] == "unsupported" and f["claimed_docs"]]
    summary = (f"{len(flags) - len(unsupported)} of {len(flags)} must-answer topics are supported by the documents."
               + (f" NOT supported (the agent will refuse these rather than guess): {', '.join(unsupported)}."
                  if unsupported else "")
               + (f" The requirements step had claimed documents for {', '.join(contradicted)}; the evidence "
                  "check overruled it." if contradicted else ""))
    req["groundability"] = {"ceiling": round(ceiling, 4), "summary": summary, "flags": flags}
    return req
