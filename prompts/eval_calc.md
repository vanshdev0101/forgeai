You are writing one test case for an AI assistant that has a calculator. The assistant serves: $audience

A passage from its documents (id $chunk_id):
"""
$passage
"""

Write ONE realistic user question that needs arithmetic on a rate or amount from this passage, applied to
quantities the user states in the question. Keep it simple and unambiguous; use one of these shapes:
  quantity x rate            ("3 people x INR 2,500 per day")
  quantity x quantity x rate ("4 people x 5 days x INR 2,500 per day")
  rate x quantity + amount
The question must contain every number the user supplies, and the passage must supply the rate.

Rules:
- expression: the exact arithmetic that answers it, using only numbers that appear in the passage or in
  your question. Use only digits, + - * / ( ) and a decimal point. No units, no commas.
- unit: the unit of the result (e.g. "days", "INR"), or empty.

Reply with JSON only:
{"question": "...", "expression": "...", "unit": "..."}
