# ForgeAI run report: shore-hr-policy-assistant

> I need an assistant that answers HR policy questions for shore staff.

**Result: 19/21 test cases pass (90%) after 2 optimisation iteration(s).** 2 still fail; each is listed below with the reason. The judge reproduced 10/10 known verdicts in its self-test.

## What still fails, and why

### prompt_defect (2): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused

- **A05** (answerable) *How often is the home-office equipment allowance provided, and what happens to any unspent balance from a previous cycle?*  
  left out: "INR 15,000".  
  Answer given: "The home-office equipment allowance is provided once every 3 years. Any unspent balance from a previous cycle does not carry forward."
- **M01** (multi_doc) *What is the maximum number of annual leave days a G3 Manager can carry over to the next year, and how often do they receive their home office equipment allowance?*  
  left out: "INR 15,000".  
  Answer given: "A G3 Manager can carry over up to ten unused annual leave days per calendar year. They receive their home office equipment allowance once every three years."

Fixes the loop tried that did not help are in the change log below; they were reverted or not applied, so these failures are what the current definition actually does.

## Scorecard per iteration

| Iteration | Change | Kept | Passed | Pass rate | Failures by category |
|---|---|---|---|---|---|
| 0 | generated agent | baseline | 18/21 | 86% | hallucination 1, prompt_defect 2 |
| 1 | added prompt rule: 'Answer every part of multi-part questions completely; if any detail is missing from your sources, state you cannot answer that specific point.' | **reverted** | 17/21 | 81% | prompt_defect 4 |
| 2 | added prompt rule: 'Never invent specific leave accrual numbers, hours, or durations; strictly state if these details are missing from your source documents.' | yes | 19/21 | 90% | prompt_defect 2 |

The loop stopped because no applicable fix was left for the remaining failures.

## Change log

### Iteration 1: prompt_defect

- **What changed:** added prompt rule: 'Answer every part of multi-part questions completely; if any detail is missing from your sources, state you cannot answer that specific point.'
- **Why:** 2 failure(s) classified as prompt_defect (A05, M01): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused. Model's rationale: This prevents incomplete answers by forcing the model to address all sub-questions and admit ignorance for missing details.
- **Score:** 18/21 -> 17/21; newly passing: C01; newly failing: A02, A08
- **Kept:** no, reverted because the pass count did not rise

### Iteration 2: hallucination

- **What changed:** added prompt rule: 'Never invent specific leave accrual numbers, hours, or durations; strictly state if these details are missing from your source documents.'
- **Why:** 1 failure(s) classified as hallucination (C01): the assistant stated things its passages do not support. Model's rationale: This prevents hallucinating unsupported numerical claims about leave entitlements when exact figures aren't provided in the reference materials.
- **Score:** 18/21 -> 19/21; newly passing: C01; newly failing: none
- **Kept:** yes

## Final results by case type

| Type | Passed |
|---|---|
| ambiguous | 1/1 |
| answerable | 9/10 |
| calculator | 2/2 |
| multi_doc | 2/3 |
| out_of_scope | 4/4 |
| ungroundable | 1/1 |

## How far to trust these numbers

- **Judge self-test:** 10/10 known verdicts reproduced (fact verdicts 100%, hallucination verdicts 100%). Probes: correct answer, the same padded with filler (verbosity), one number changed, one invented claim.
- **Test set:** 21 generated cases {'answerable': 10, 'multi_doc': 3, 'ambiguous': 1, 'out_of_scope': 4, 'ungroundable': 1, 'calculator': 2}; 13 candidates were dropped because their expected answer could not be verified ({'answerable': 1, 'multi_doc': 5, 'ambiguous': 5, 'calculator': 2}). Prompts: `prompts/eval_*.md`.
- **Same model family:** the agent (4b), the eval generator and the judge (9b) are all qwen3.5. The judge is a different size and is never told which model answered, but shared blind spots are possible.
- **Eval cases can be wrong:** facts are verified against the source text, but the question a fact is attached to is written by a model; a calculator case whose question both independent derivations misread the same way would survive.

## Requirements and groundability

3 of 4 must-answer topics are supported by the documents. NOT supported (the agent will refuse these rather than guess): seafarer_redirects.

- **leave_entitlements_and_procedures**: supported (llm_verified, best passage 0.849). quote: 'Female employees are eligible for twenty-six weeks of paid maternity leave following childbirth. Male employees receive ten working days of paid paternity leave'
- **remote_work_guidelines**: supported (llm_verified, best passage 0.8066). quote: 'Remote work is permitted strictly up to 2 days per week, contingent upon explicit approval from the reporting manager.'
- **business_travel_and_expenses**: supported (llm_verified, best passage 0.8052). quote: 'Receipt Requirements: Original physical or digital receipts are mandatory for reimbursement of any single expense exceeding INR 500.'
- **seafarer_redirects**: unsupported (llm_verified, best passage 0.6628). The documents contain policies on travel expenses, remote work ethics, and leave entitlements for shore staff. They do not mention 'seafarer_redirects', crewing policies specific to seafarers, or inst

## Tools

| Tool | Attached | Need signal | Evidence |
|---|---|---|---|
| csv_lookup | no | - | - |
| calculator | yes | accrual | leave_policy.pdf#0: ...days G5 Director: 30 days Leave accrues monthly at a rate of one tw |
| weather | no | - | - |
| current_date | yes | eligibility | remote_work_conduct_policy.pdf#2: ... Conflicts of interest must be declared within 7 days |

## Retrieval

chunk_words=250, overlap=40, k=4, min_score=0.579. Calibration: off-topic probes up to 0.5586, in-scope questions down to 0.6441 (sample_questions); gate role: refuses off-topic on its own.

## Cost

196 local LLM calls, 256101 tokens, 881 s wall time.

| Stage | Calls | Tokens | Seconds |
|---|---|---|---|
| inventory | 3 | 3126 | 12.7 |
| questions | 1 | 1119 | 10.8 |
| requirements | 1 | 1751 | 12.6 |
| groundability | 4 | 4625 | 13.6 |
| generate | 1 | 1017 | 4.1 |
| evalgen | 38 | 21726 | 93.8 |
| judge_selftest | 11 | 5905 | 13.3 |
| eval_and_optimize | 137 | 216832 | 720.2 |
