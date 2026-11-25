Write a realistic internal document for $company.

Title: $title
Readers: $audience
Purpose: $purpose

It MUST contain every one of these facts, with the numbers and names written exactly as given:
$facts

Rules:
- 500 to 800 words, in Markdown: a title line, a short version/effective-date line, then sections with
  headings. Use a small table where it fits naturally.
- Do not add any other numbers, amounts, dates, durations or limits beyond the facts above; describe
  everything else in words. (The document is used to test an assistant, so every figure must be known.)
- Plain, professional policy language. No placeholders like [Company Name].

Reply with JSON only:
{"markdown": "<the full document>"}
