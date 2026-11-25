You are writing the persona section of a system prompt for an AI assistant. The scope list, the list of
topics to refuse, and the answer format will be appended automatically after your text, so do NOT write
those yourself and do NOT give any output-format instructions.

Requirements:
$requirements

Write, addressed to the assistant in the second person ("You are ..."):
- who it is and who it serves (the audience),
- how it should sound (the tone), and how much detail suits the audience,
- how to handle a question that is partly answerable: answer the supported part, say plainly what the
  documents do not cover,
- that it must never guess at policy, numbers or dates that are not in its sources.

Keep it under 150 words.

Also write the refusal message the assistant will use word-for-word when it cannot answer: one short
sentence in the same tone, without apologising more than once.

Reply with JSON only:
{"persona": "<the text>", "refusal_message": "<one sentence>", "description": "<one sentence for a catalogue: who it serves and what it answers>"}
