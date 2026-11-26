# Human audit of this run

Every failing case was read by hand after the run. The factory's own report (`report.md`) is unchanged;
this file records where a human disagrees with it.

Score reported by the factory: **17/21 (81%)**. Of the 4 failures, **1 is a genuine agent error and 3 are
defective test cases**, so the agent's real accuracy on this set is closer to 20/21.

| Case | Factory says | Human verdict | Reason |
|---|---|---|---|
| A04 | hallucination | **agent error (agree)** | Its own figures give USD 28,840 on a USD 28,000 order (+3%), but it reports +7%, and it guesses whether the 15% surcharge applies before or after the 8% discount. |
| M02 | prompt_defect | test defect | The question asks about Nordic Marine Supply's return policy. The agent's 10% restocking fee is Nordic's figure; the expected 15% belongs to the other supplier. |
| B03 | prompt_defect | test defect | "What extra % will I pay for urgent air freight?" The agent's 15% surcharge is the answer; the test also expects the 8% volume discount, inherited from the compound question it rewrites. |
| C01 | hallucination | test defect | "4 turbocharger bearings from Nordic Marine Supply": the catalogue lists bearings for several engines, so the question is ambiguous. The agent asks which engine; the test expects one particular row's price. |

All three test defects come from the same known limit: with two suppliers offering parallel terms, the
generator can still write compound or under-specified questions (see README, "Known limits of the evals").
They were left in place rather than tuned away, so the committed run is what the factory produced unattended.
