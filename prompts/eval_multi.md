You are writing one test case for an AI assistant. The assistant serves: $audience
Its purpose: $summary

Two passages from different parts of its documents:

Passage A (id $id_a):
"""
$passage_a
"""

Passage B (id $id_b):
"""
$passage_b
"""

Write ONE realistic user question whose correct answer needs information from BOTH passages (for example a
situation that involves two rules, or a comparison).

Rules:
- facts_a: 1 or 2 short facts (at most 8 words each) copied WORD FOR WORD from passage A that the answer must state.
- facts_b: 1 or 2 short facts (at most 8 words each) copied WORD FOR WORD from passage B that the answer must state.
- Do not mention "passage A/B" or "the document" in the question.
- Passage A is from $doc_a and passage B from $doc_b. If they describe different suppliers, products or
  groups, the question must name which one each part refers to, and must not combine figures that belong to
  different ones into a single answer.
- Your answer must state every fact you list.
$avoid

Reply with JSON only:
{"question": "...", "answer": "<correct answer>", "facts_a": ["..."], "facts_b": ["..."]}
