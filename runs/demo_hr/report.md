# ForgeAI run report: shore-hr-policy-assistant

> I need an assistant that answers HR policy questions for shore staff.

**Result: 20/23 test cases pass (87%) after 1 optimisation iteration(s).** 3 still fail; each is listed below with the reason. The judge reproduced 10/10 known verdicts in its self-test.

## What still fails, and why

### prompt_defect (3): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused

- **A04** (answerable) *How often is the home-office equipment allowance provided and what are acceptable uses for it?*  
  left out: "INR 15,000".  
  Answer given: "The home-office equipment allowance is provided once every three years. Acceptable uses include purchasing ergonomic furniture, upgrading internet connectivity, or buying necessary hardware like laptops and monitors."
- **M01** (multi_doc) *What are the annual leave entitlement days for a G2 Senior Associate and what travel class is required for international operations between Mumbai and Singapore?*  
  left out: "must select premium economy class.".  
  Answer given: "A G2 Senior Associate gets 21 annual leave days per year. For international flights (6+ hours), Premium Economy class is required."
- **C01** (calculator) *If an employee works remotely for 2 approved days in a week, what is the total maximum number of hours they must be available during core working time?*  
  left out: "12".  
  Answer given: "The policy states that remote work is permitted up to **2 days per week** and requires availability from **10:00 to 16:00 IST**. However, it does not specify the total number of hours across those two days. I cannot calc..."

Fixes the loop tried that did not help are in the change log below; they were reverted or not applied, so these failures are what the current definition actually does.

## Scorecard per iteration

| Iteration | Change | Kept | Passed | Pass rate | Failures by category |
|---|---|---|---|---|---|
| 0 | generated agent | baseline | 20/23 | 87% | prompt_defect 3 |
| 1 | added prompt rule: 'If any part of a multi-part question is missing from your sources, state you cannot answer that specific detail rather than providing partial information.' | **reverted** | 20/23 | 87% | prompt_defect 3 |

The loop stopped because no applicable fix was left for the remaining failures.

## Change log

### Iteration 1: prompt_defect

- **What changed:** added prompt rule: 'If any part of a multi-part question is missing from your sources, state you cannot answer that specific detail rather than providing partial information.'
- **Why:** 3 failure(s) classified as prompt_defect (A04, M01, C01): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused. Model's rationale: This prevents incomplete answers when source documents lack details for parts of the query.
- **Score:** 20/23 -> 20/23; newly passing: none; newly failing: none
- **Kept:** no, reverted because the pass count did not rise

## Final results by case type

| Type | Passed |
|---|---|
| ambiguous | 3/3 |
| answerable | 9/10 |
| calculator | 1/2 |
| multi_doc | 2/3 |
| out_of_scope | 4/4 |
| ungroundable | 1/1 |

## How far to trust these numbers

- **Judge self-test:** 10/10 known verdicts reproduced (fact verdicts 100%, hallucination verdicts 100%). Probes: correct answer, the same padded with filler (verbosity), one number changed, one invented claim.
- **Test set:** 23 generated cases {'answerable': 10, 'multi_doc': 3, 'ambiguous': 3, 'out_of_scope': 4, 'ungroundable': 1, 'calculator': 2}; 13 candidates were dropped because their expected answer could not be verified ({'answerable': 1, 'multi_doc': 8, 'ambiguous': 2, 'calculator': 2}). Prompts: `prompts/eval_*.md`.
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

159 local LLM calls, 184278 tokens, 695 s wall time.

| Stage | Calls | Tokens | Seconds |
|---|---|---|---|
| inventory | 3 | 3126 | 16.2 |
| questions | 1 | 1119 | 13.6 |
| requirements | 1 | 1751 | 13.5 |
| groundability | 4 | 4625 | 11.1 |
| generate | 1 | 1017 | 3.4 |
| evalgen | 41 | 23985 | 105.7 |
| judge_selftest | 11 | 5946 | 12.4 |
| eval_and_optimize | 97 | 142709 | 519.5 |
