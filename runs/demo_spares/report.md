# ForgeAI run report: vessel-spare-parts-assistant

> I need an assistant that helps vessel superintendents find ship spare parts for our main and auxiliary engines, check prices, stock and lead times, and compare supplier terms before raising a purchase request.

**Result: 17/21 test cases pass (81%) after 2 optimisation iteration(s).** 4 still fail; each is listed below with the reason. The judge reproduced 12/12 known verdicts in its self-test.

## What still fails, and why

### hallucination (2): the assistant stated things its passages do not support

- **A04** (answerable) *If I order spare parts worth USD 28,000 from Nordic Marine Supply for urgent delivery via air freight to the vessel's port, what is my total cost percentage increase compared to standard terms?*  
  stated things its passages do not support: "The total cost increases by **7%** compared to standard terms"; "$24,640".  
  Answer given: "The total cost increases by **7%** compared to standard terms for your USD 28,000 order from Nordic Marine Supply with urgent air freight delivery.  **Calculation breakdown:** - Volume discount (orders > $25,000): -8% → ..."
- **C01** (calculator) *What is the total cost to order 4 turbocharger bearings from Nordic Marine Supply?*  
  stated things its passages do not support: "The catalogue lists only one turbocharger bearing (YAN-0556) for Yanmar engines and another (WRT-0556) for Wartsila engines."; "Neither is supplied by Nordic Marine Supply with a stock quantity of 4 or more that matches the request exactly".  
  Answer given: "The catalogue lists only one turbocharger bearing (YAN-0556) for Yanmar engines and another (WRT-0556) for Wartsila engines. Neither is supplied by Nordic Marine Supply with a stock quantity of 4 or more that matches the..."

### prompt_defect (2): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused

- **M02** (multi_doc) *A superintendent in Singapore needs to order spare parts exceeding USD 25,000 from Nordic Marine Supply and must inquire about the return policy for items sent back; what are the applicable volume discount percentage and restocking fee percentage?*  
  left out: "15%".  
  Answer given: "For orders exceeding USD 25,000 with Nordic Marine Supply: The applicable volume discount is **8%**. For returns within the permitted timeframe (30 days), a restocking fee of **10%** applies to the original invoice value..."
- **B03** (ambiguous) *I'm ordering spare parts worth 28k from Nordic Marine Supply for air freight super urgent. What's the extra % I'll pay versus normal?*  
  left out: "8%".  
  Answer given: "Utilizing urgent air freight with Nordic Marine Supply triggers a non-negotiable surcharge of 15% on the order value, regardless of volume discounts."

Fixes the loop tried that did not help are in the change log below; they were reverted or not applied, so these failures are what the current definition actually does.

## Scorecard per iteration

| Iteration | Change | Kept | Passed | Pass rate | Failures by category |
|---|---|---|---|---|---|
| 0 | generated agent | baseline | 16/21 | 76% | hallucination 2, prompt_defect 2, retrieval_miss 1 |
| 1 | added prompt rule: 'Never infer percentages or specific fee structures from partial data; explicitly state that exact figures are unavailable if not fully supported by a single source.' | **reverted** | 15/21 | 71% | hallucination 3, prompt_defect 3 |
| 2 | added prompt rule: 'Always extract every specific numerical value, percentage, or fee explicitly requested from your documents before answering.' | yes | 17/21 | 81% | hallucination 2, prompt_defect 2 |

The loop stopped because no applicable fix was left for the remaining failures.

## Change log

### Iteration 1: hallucination

- **What changed:** added prompt rule: 'Never infer percentages or specific fee structures from partial data; explicitly state that exact figures are unavailable if not fully supported by a single source.'
- **Why:** 2 failure(s) classified as hallucination (A04, A07): the assistant stated things its passages do not support. Model's rationale: This prevents hallucinating unsupported cost calculations and warranty documentation requirements when the provided documents lack complete details.
- **Score:** 16/21 -> 15/21; newly passing: none; newly failing: M01
- **Kept:** no, reverted because the pass count did not rise

### Iteration 2: prompt_defect

- **What changed:** added prompt rule: 'Always extract every specific numerical value, percentage, or fee explicitly requested from your documents before answering.'
- **Why:** 2 failure(s) classified as prompt_defect (M02, B03): the assistant had the passage but answered incompletely, cited wrongly, or answered something it should have refused. Model's rationale: This prevents missing required data points like discounts and fees by enforcing a complete extraction of all numeric answers.
- **Score:** 16/21 -> 17/21; newly passing: A07; newly failing: none
- **Kept:** yes

- Iteration 3, **prompt_defect**: no fix applied (the model proposed a rule already in the prompt: 'Always extract every specific numerical value, percentage, or fee explicitly requested from your documents before answering.').

## Final results by case type

| Type | Passed |
|---|---|
| ambiguous | 2/3 |
| answerable | 9/10 |
| calculator | 0/1 |
| csv_lookup | 2/2 |
| multi_doc | 1/2 |
| out_of_scope | 2/2 |
| ungroundable | 1/1 |

## How far to trust these numbers

- **Judge self-test:** 12/12 known verdicts reproduced (fact verdicts 100%, hallucination verdicts 100%). Probes: correct answer, the same padded with filler (verbosity), one number changed, one invented claim.
- **Test set:** 21 generated cases {'answerable': 10, 'multi_doc': 2, 'ambiguous': 3, 'out_of_scope': 2, 'ungroundable': 1, 'calculator': 1, 'csv_lookup': 2}; 17 candidates were dropped because their expected answer could not be verified ({'answerable': 1, 'multi_doc': 10, 'ambiguous': 1, 'calculator': 5}). Prompts: `prompts/eval_*.md`.
- **Same model family:** the agent (4b), the eval generator and the judge (9b) are all qwen3.5. The judge is a different size and is never told which model answered, but shared blind spots are possible.
- **Eval cases can be wrong:** facts are verified against the source text, but the question a fact is attached to is written by a model; a calculator case whose question both independent derivations misread the same way would survive.

## Requirements and groundability

5 of 6 must-answer topics are supported by the documents. NOT supported (the agent will refuse these rather than guess): catalogue_limitation_notice.

- **spare_parts_lookup**: supported (llm_verified, best passage 0.73). quote: 'part_number: YAN-0160; description: fuel injector nozzle; compatible_engine: Yanmar 6EY18; unit_price_usd: 472.09; stock_qty: 4'
- **pricing_and_lead_time**: supported (llm_verified, best passage 0.7266). quote: 'unit_price_usd: 485.23; ... supplier: Asia Pacific Ship Parts; lead_time_days: 0; min_order_qty: 2'
- **supplier_terms_comparison**: partial (llm_verified, best passage 0.8082). quote: 'These provisions apply exclusively to orders for ship spare parts placed by vessel superintendents or purchasing staff located at our shore offices in Mumbai an'; missing: The passages contain
- **urgent_service_fees**: supported (llm_verified, best passage 0.7646). quote: 'An urgent air freight surcharge adds a 20% charge on the order value for expedited shipments via air cargo.'
- **regional_compliance_check**: supported (llm_verified, best passage 0.7376). quote: 'Operational Guidelines for Superintendents Vessel superintendents are expected to coordinate closely with shore offices in Mumbai before initiating any procurem'
- **catalogue_limitation_notice**: unsupported (llm_verified, best passage 0.6445). The required topic is to inform users that information is strictly limited to parts explicitly listed in a CSV and no data exists for non-standard or discontinued items. The provided passages discuss 

## Tools

| Tool | Attached | Need signal | Evidence |
|---|---|---|---|
| csv_lookup | yes | supported topics sourced from ['spare_parts_catalogue.csv'] | CSV present in the document folder |
| calculator | yes | prices | spare_parts_catalogue.csv#2: ...lves; compatible_engine: Wartsila 6L32; unit_price_usd: 14 |
| weather | no | - | - |
| current_date | yes | lead times | nordic_marine_supply_terms.pdf#1: ...ly held in stock, we commit to shipping within 3 work |

## Retrieval

chunk_words=250, overlap=40, k=4, min_score=0.576. Calibration: off-topic probes up to 0.5556, in-scope questions down to 0.6148 (sample_questions); gate role: refuses off-topic on its own.

## Cost

219 local LLM calls, 388069 tokens, 1187 s wall time.

| Stage | Calls | Tokens | Seconds |
|---|---|---|---|
| inventory | 3 | 4157 | 16.5 |
| questions | 1 | 1213 | 13.1 |
| requirements | 1 | 1999 | 18.5 |
| groundability | 6 | 8981 | 23.6 |
| generate | 1 | 1342 | 4.8 |
| evalgen | 40 | 34585 | 120.5 |
| judge_selftest | 15 | 9705 | 16.8 |
| eval_and_optimize | 152 | 326087 | 972.9 |
