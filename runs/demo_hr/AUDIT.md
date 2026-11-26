# Human audit of this run

Every failing case was read by hand after the run. The factory's own report (`report.md`) is unchanged;
this file records where a human disagrees with it.

Score reported by the factory: **19/21 (90%)**. Both failures are **defective test cases**; the agent's
answers are correct and complete for what was asked.

| Case | Factory says | Human verdict | Reason |
|---|---|---|---|
| A05 | prompt_defect | test defect | "How often is the home-office equipment allowance provided, and what happens to unspent balance?" The agent answers both parts correctly (once every 3 years; does not carry forward). The test also expects the amount, INR 15,000, which the question does not ask for. |
| M01 | prompt_defect | test defect | Same pattern: "how often do they receive their home-office equipment allowance" is answered correctly; the expected INR 15,000 is not asked for. |

Both come from a known limit of the relevance check: it keeps any fact the generator's own reference answer
mentions, and a verbose reference answer mentioned the amount (see README, "Known limits of the evals"). They
were left in place rather than tuned away, so the committed run is what the factory produced.

Note: this run was started from the command line with `--answers demos/hr/answers.json` and an output folder
of `runs/demo_hr_new`, then moved here; the `docs_dir` path in `agent_def.json` is relative and still resolves.
