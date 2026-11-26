You are writing one test case for an AI assistant. The assistant serves: $audience
Its purpose: $summary

Here is one passage from its documents (id $chunk_id):
"""
$passage
"""

Write ONE question a real user of this assistant would plausibly ask that this passage answers, and the
facts a correct answer must contain.

Rules:
- The question must be answerable from this passage alone. Do not mention "the passage" or "the document".
- The collection also contains: $others. If the answer depends on which supplier, product, grade, office or
  document it refers to (for example two suppliers both have a discount rule), the question MUST name it, so
  that only one correct answer exists.
- key_facts: 1 to 3 short facts (at most 8 words each) COPIED WORD FOR WORD from the passage: a number with
  its unit, a name, a short phrase. Each must be part of the answer to THIS question; do not list other facts
  from the passage. Do not paraphrase them.
- Prefer facts with numbers, limits, names or conditions over vague statements.
$avoid
Reply with JSON only:
{"question": "...", "answer": "<one or two sentence correct answer>", "key_facts": ["...", "..."]}
