You are checking an assistant's answer for invented information. The assistant was only allowed to use
the passages below (and the tool results listed).

Passages it was given:
"""
$passages
"""

Tool results it received:
$tool_results

The user's question (numbers and situations the user states are given, not invented):
$question

Answer to check:
"""
$answer
"""

List every specific claim in the answer (a number, rule, name, date, condition, or a change of "may" to
"must" and similar) that the passages, tool results and the user's question do NOT support. A claim that
follows from simple arithmetic on supported numbers counts as supported. Courtesy phrases, offers of help
and "according to the policy" are not claims: never list them. Copy each unsupported claim word for word
from the answer.

Reply with JSON only:
{"unsupported_claims": ["<exact words from the answer>", ...]}
