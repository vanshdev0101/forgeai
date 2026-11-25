You are auditing whether an AI assistant's documents can actually answer a required topic. Be strict:
the assistant will be told to answer this topic from these passages, and if they do not contain the
information it will make something up.

Required topic: $topic
What users will ask: $details

The best-matching passages from the documents:
$passages

Decide:
- "supported": the passages contain the specific facts needed to answer typical questions on this topic.
- "partial": the passages answer some of these questions but clearly not others.
- "unsupported": the passages are only loosely related, or do not contain the needed facts.

For "supported" or "partial", copy ONE sentence or phrase from the passages, word for word, that shows the
support, and write two short questions a real user might type that these passages answer (plain wording, the
way a user asks, not the way the document is written). For "unsupported", say what is missing.

Reply with JSON only:
{"verdict": "supported" | "partial" | "unsupported",
 "quote": "<exact words copied from a passage, or empty>",
 "missing": "<what users will ask that the passages cannot answer, or empty>",
 "sample_questions": ["<question 1>", "<question 2>"]}
