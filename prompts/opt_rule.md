You are improving the system prompt of an AI assistant after testing. You may add exactly ONE short rule.
Do not rewrite the prompt.

Current system prompt:
"""
$system_prompt
"""

Failure category: $category ($category_meaning)

Failing test cases:
$failures

Write one general rule (at most 40 words) that would prevent this kind of failure on questions like these,
including ones not listed here. Rules about behaviour only: do NOT include any specific answer, number,
name or fact from the cases above (that would be memorising the test, not fixing the assistant), and do not
contradict the existing prompt.

Reply with JSON only:
{"rule": "<the rule>", "why": "<one sentence: what in the failures it addresses>"}
