You are grading an assistant's answer. You check ONE fact only. Ignore style, length and anything else in
the answer.

Question asked: $question
Fact the answer must state: "$fact"
(It comes from this sentence of the source document: "$source")

Answer to grade:
"""
$answer
"""

Does the answer convey this fact? Count it as YES when the answer expresses the same meaning in different
words, word order or tense, or writes numbers and dates differently ("two" for 2, "December 31st" for
"31 December", "no carry-over" for "does not carry over"). Count it as NO if the answer leaves it out, gives
a different number, or says something that contradicts it.

If YES, copy the exact words from the answer that state it.

Reply with JSON only:
{"states_fact": true|false, "answer_span": "<exact words copied from the answer, or empty>"}
