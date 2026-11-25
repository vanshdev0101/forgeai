# ForgeAI

A factory that turns a one-paragraph brief plus a folder of documents into a working, tested
RAG agent: requirements, agent definition, generated evals, judged results, targeted fixes,
and an honest report. Everything runs locally on small open models via Ollama.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Runtime spine: LLM wrapper, RAG, tool registry, agent-definition schema, generic runner (req 8) | done |
| 2 | Intake interviewer (req 1), groundability guard (req 2), agent generator (req 3) | done |
| 3 | Eval generator (req 4) + judge (req 5) | done |
| 4 | Critic-optimizer loop (req 6) + honest report (req 7) | next |
| 5 | Two full demo runs (req 9) | |

The groundability guard was planned for a later phase but moved into Phase 2: live runs showed the
generator produces wrong agents without it (see below).

## Setup

```
ollama pull qwen3.5:4b qwen3.5:9b nomic-embed-text   # or the -8k context variants used by default
pip install numpy requests                            # the only Python deps
```

Models are configurable: `FORGE_GEN_MODEL`, `FORGE_JUDGE_MODEL`, `FORGE_EMBED_MODEL`, `OLLAMA_HOST`.

## Build an agent

```
python forge.py --brief "I need an assistant that answers HR policy questions for shore staff" \
                --docs path/to/docs --out runs/hr            # interviews you on the terminal
python forge.py --brief brief.txt --docs docs/ --out runs/x --auto              # unattended: defaults
python forge.py --brief brief.txt --docs docs/ --out runs/x --answers ans.json  # scripted answers
```

Artifacts in `--out`: `inventory.json`, `interview.json`, `requirements.json` + `requirements.md`
(with a groundability verdict per topic), `agent_def.json`, `generation_log.json` (tool evidence,
retrieval calibration, token usage per stage). Factory stages use `qwen3.5-9b`; the agents it builds run
on `qwen3.5-4b`. One run takes about 45-60 s on this laptop.

## How the factory builds (and why)

Every rule below was added after a live run went wrong.

- **Intake.** At most 5 clarifying questions, capped in code. Each comes with a default assumption; an
  unanswered question uses it and is recorded as `assumed`, never passed off as the requester's answer.
  Requirements record what the requester *needs*, including topics no document covers, so gaps stay
  visible.
- **Groundability guard (req 2).** The requirements step's own claims about which documents cover a topic
  are not trusted: in a live run the factory model claimed a salary figure was in the assignment PDF,
  which contains none. Each must-answer topic is checked instead: (1) a retrieval gate with no LLM, (2) the
  model reads the retrieved passages and must quote one verbatim, (3) code verifies the quote is really in
  the passages. Unsupported topics are refused by the generated agent rather than guessed at.
- **System prompt.** The model writes the persona and tone; the scope list, the "not covered" list and the
  must-refuse list are appended from the requirements verbatim, so no rule can be silently dropped.
- **Tool selection is evidence-based, not model-chosen.** Four LLM variants were tried (propose, repair,
  justify with an example question, independent blind audit) and they swung between attaching tools "just
  in case" and rejecting needed ones. Each tool now has two generic tests, and is attached only if both
  hold: *need* (the brief, requirements or clarifications ask for what it does) and *feasibility* (passages
  retrieved for **supported** topics contain what it works on: rates and prices for the calculator, time
  windows for the date tool, a CSV-sourced topic for `csv_lookup`; weather only if the brief asks for it).
  The log records the matched words and the passage as evidence. Live result: the HR agent gets
  `csv_lookup`, `calculator` and `current_date`; the assignment-FAQ agent gets none (the calculator had
  evidence but no need; the date tool had a need, "deadline", but the deadline is not in the documents).
- **Retrieval threshold, calibrated per corpus.** `nomic-embed-text` compresses scores. The in-scope side
  is measured with user-style questions written by the guard (topic labels score about 0.1 higher than
  real questions, which overstated separation); the off-topic side with 12 fixed probes. If they separate,
  the threshold sits above the probes and refuses off-topic questions on its own (HR corpus: probes at most
  0.53, questions at least 0.64). If they overlap (assignment PDF: probes up to 0.60, real questions down to
  0.54), it is only a recall floor and the agent's scope rules do the refusing.

## How the factory tests what it built (and why)

**Eval generator (req 4).** At least 20 cases generated from the documents; every prompt is in
`prompts/eval_*.md`. The factory model only *phrases* questions; what counts as correct is checked or
computed in code, because a weak model writing its own tests otherwise writes easy or wrong ones.

| Type | Expected answer comes from |
|---|---|
| answerable | key facts the model proposes, kept only if short, present in the source passage, and stated in the model's own reference answer (relevance check: a flight-class question once listed the allowance as its facts) |
| multi_doc | a verified fact from each of two passages in different documents |
| ambiguous | an informal rewrite of an answerable case, kept only if an independent check says it asks for the same information (one rewrite turned "domestic work travel" into "working at home") |
| calculator | the model's expression, run by the calculator; every number must appear in the passage or question, and a second call that never sees the expression must derive the same result |
| csv_lookup | a real cell, read from the CSV (no LLM) |
| out_of_scope, ungroundable | must-refuse topics and topics the guard found unsupported; must be refused |

Sentence-long "facts" (the 9b model often copies whole sentences) are cut to their numeric phrases, and
near-duplicate questions are rejected. Every rejected case is kept in `evals.json` under `dropped`, with
the reason.

**Judge (req 5).** Deterministic checks first, the 9b model only where code cannot decide, and the
model's verdicts checked again by code:

- refusal correct, grounding (cites an expected source document or used the expected tool) and key facts
  (normalised: number words, ordinals, Indian digit grouping, CSV column names, light stemming) in code;
- facts code can't match go to a per-fact yes/no question; a "yes" counts only if its quoted span is really
  in the answer and carries every number of the fact, so a judge that accepts a changed number is overruled;
- hallucination: the model lists unsupported claims, given the passages, tool results and the question;
  a claim counts only if quoted from the answer and checkable (courtesy filler and verbatim restatements are
  filtered in code).

Bias defences: binary per-fact questions instead of quality scores (verbosity), no pairwise comparison
(position), judge model differs from the agent model and is never told who wrote the answer
(self-preference). **The judge is tested every run**: a self-test grades probes whose verdict is known
(correct answer, the same padded with filler, a changed number, an invented claim) and the result is in the
scorecard. It caught the claims judge flagging courtesy filler as hallucination, which led to the filter.

Live, on the two development briefs: HR policy 20/22 (91%), self-test 12/12; assignment FAQ 15/21 (71%),
self-test 11/11. Every failure was audited by hand; the remaining ones are agent errors (a wrong
entitlement, an invented carry-over rule, "may" turned into "must", "3-4 tools" turned into "at least four").

**Known limits of the evals.** An independent derivation can share the generator's misreading of a
confused calculator question (seen once); a question-only "is this sensible?" check was tried and rejected
because it threw out more good cases than bad. The 9b fact judge leans strict on paraphrases in prose-heavy
documents, so recall on such corpora is a slight underestimate.

## Run an agent

```
python -m runtime.runner examples/smoke/agent_def.json           # chat
python -m runtime.runner examples/smoke/agent_def.json --debug   # chat, show retrieval + tool calls
python -m runtime.runner examples/smoke/agent_def.json --ask "How many sick days do I get?"   # JSON trace
```

The runner is generic: it loads any definition that validates against
`schemas/agent_def.schema.json`. Nothing agent-specific is hard-coded.

## How the runner answers (and why)

Each design choice below came from watching `qwen3.5:4b` fail on the smoke agent.

1. **Retrieve** top-k chunks with cosine >= `min_score`.
2. **Deterministic refusal** when nothing clears the threshold and the agent has no tool that works
   without documents (`current_date`, `weather`). No LLM call, so no chance to hallucinate.
3. **Stage 1, JSON mode, no tools offered.** With tools offered up front the 4b model called them on
   almost every question and blended junk results into correct answers. Instead the answer object has a
   `need_tool` field the model sets when it needs arithmetic, a table lookup or the date.
4. **Stage 2, tool loop** (only if requested). Free-text turns, because JSON mode makes the model skip
   tool calls and do arithmetic in its head. Identical calls execute once; the last round withholds tools
   so the loop terminates; then one JSON-mode finalize turn.
5. **Contract enforcement.** Passages are shown as short tags (`S1`, `S2`), which a 4b model copies
   reliably, and mapped back to chunk ids. Invented citations are dropped and recorded. Uncited answers,
   non-standard refusals, over-length answers and unparseable JSON are recorded as `violations` in the
   trace rather than hidden, so the judge can score them.

6. **Deterministic decoding** (temperature 0, fixed seed) for answer turns. At temperature 0.2 the same
   question gave a correct answer 3 times in 4 and nonsense once; the optimizer compares scores before and
   after each fix, and that noise would swamp the effect of the fix. Eval generation opts back into sampling.

Smoke-agent effect of these changes: 25 LLM calls / 28 s for five questions down to 3-4 calls / ~7 s,
with out-of-scope questions refused at zero calls.

## Tests

```
python tests/test_phase1.py     # runtime, offline: fake embeddings, stubbed LLM; no Ollama needed
python tests/test_phase2.py     # factory, offline: stubbed factory model
python tests/mutate_phase1.py   # break each runtime guard in turn; the suite must fail every time
python tests/mutate_phase2.py   # same for the factory
python tests/test_phase3.py     # eval generator + judge, offline
python tests/mutate_phase3.py
python tests/smoke_live.py      # live run against Ollama
```

All three mutation suites pass: 18/18, 33/33 and 30/30 mutants caught, with the clean suite passing before
and after. The harness runs with `PYTHONDONTWRITEBYTECODE=1`: a same-size mutation restored within the
same second once left stale bytecode running, which made later "caught" results meaningless.

## Robustness for unattended runs

- `llm.preflight()` checks Ollama is up and the models are pulled before anything starts; failures
  print one line with the fix (`ollama serve`, `ollama pull <model>`) and exit 2, no traceback.
- PDFs: running headers/footers (short lines repeated exactly on at least half the pages, page numbers
  normalised) are stripped before chunking, so they don't pollute retrieval or citations. Lines that
  differ only by a number, such as table rows, are kept.

## Known limitations

- Answers are stateless per question (no conversation memory). The evals score single turns; add history
  if a brief needs follow-ups.
- The 4b model still makes reasoning slips, e.g. transcribing "18.5%" as 1.18 into a correct calculator
  call. The runner cannot fix that; the judge (Phase 3) is meant to catch it.
- Brute-force cosine retrieval; fine for a few thousand chunks.
