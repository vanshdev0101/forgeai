You are writing the requirements document for an AI assistant, from the requester's brief and their
answers to clarifying questions. A separate step will check which requirements the documents can support,
so record what the REQUESTER NEEDS, not only what the documents happen to contain.

Requester's brief:
"""
$brief
"""

Clarifications (source "requester" = their answer, "assumed" = our default because they did not answer):
$clarifications

Documents available:
$inventory

Reply with JSON only, in exactly this shape:
{
  "name": "<kebab-case name, e.g. hr-policy-assistant>",
  "summary": "<1-2 sentences: what the assistant is for>",
  "audience": "<who will use it>",
  "tone": "<e.g. friendly and plain-spoken, formal and precise>",
  "answer_length": "short" | "medium" | "detailed",
  "must_answer_topics": [
    {"topic": "<short label>", "details": "<what kind of questions this covers>",
     "source_docs": ["<document names you believe cover it; [] if none do>"]}
  ],
  "must_refuse_topics": [
    {"topic": "<short label>", "reason": "<why the assistant must decline>"}
  ],
  "assumptions": ["<every decision you made that the requester did not state explicitly>"]
}

Rules:
- must_answer_topics: 3 to 10 topics, each a distinct area of questions from the brief. Include topics the
  brief asks for even if no document covers them (with "source_docs": []).
- source_docs must only contain names from the document list above.
- must_refuse_topics: 2 to 6 concrete categories a user might actually ask about. Always include anything
  the clarifications say to refuse. Consider, where they fit this assistant: personal or confidential data
  about specific individuals; legal, medical or financial advice; decisions only a human may make
  (approving, granting, negotiating); topics the brief asks for that no document covers. Do not list
  vague categories such as "anything out of scope"; that rule is added automatically.
- Do not invent facts about the documents.
