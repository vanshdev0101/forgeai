# ForgeAI

A factory that turns a one-paragraph brief plus a folder of documents into a working, tested
RAG agent: requirements, agent definition, generated evals, judged results, targeted fixes,
and an honest report. Everything runs locally on small open models via Ollama.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Runtime spine: LLM wrapper, RAG, tool registry, agent-definition schema, generic runner (req 8) | done |
| 2 | Intake interviewer (req 1), groundability guard (req 2), agent generator (req 3) | done |
| 3 | Eval generator (req 4) + judge (req 5) | next |
| 4 | Critic-optimizer loop (req 6) + honest report (req 7) | |
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
python tests/smoke_live.py      # live run against Ollama
```

Both mutation suites currently pass: 18/18 and 33/33 mutants caught, with the clean suite passing before
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
