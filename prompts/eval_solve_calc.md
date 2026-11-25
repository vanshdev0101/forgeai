Solve a user's question using a source passage and arithmetic.

Source passage:
"""
$passage
"""

Question: $question

Write the single arithmetic expression that computes the answer, using numbers from the passage and the
question. Use only digits, + - * / ( ) and a decimal point: no units, no commas. If the question is unclear
or cannot be answered from the passage, set "answerable" to false.

Reply with JSON only:
{"answerable": true|false, "expression": "<arithmetic>"}
