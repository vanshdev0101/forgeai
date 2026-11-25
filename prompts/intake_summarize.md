You are cataloguing a document that an AI assistant will answer questions from.

Document name: $name
Document type: $kind
$extra
Beginning of the document:
"""
$excerpt
"""

Reply with JSON only:
{"summary": "<2-3 sentences: what this document covers and who it is for>",
 "topics": ["<5 to 10 short topic labels this document can answer questions about>"]}

Rules: describe only what is actually in the text above. Do not guess at content you cannot see.
