# ForgeAI

A factory that turns a one-paragraph brief plus a folder of documents into a working, tested
RAG agent: requirements, agent definition, generated evals, judged results, targeted fixes,
and an honest report. Everything runs locally on small open models via Ollama.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Runtime spine: LLM wrapper, RAG, tool registry, agent-definition schema, generic runner | done |
| 2 | Intake interviewer + agent generator | next |
| 3 | Eval generator + judge | |
| 4 | Critic-optimizer loop + report | |
| 5 | Groundability guard | |
| 6 | Two full demo runs | |

## Setup

```
ollama pull qwen3.5:4b qwen3.5:9b nomic-embed-text   # or the -8k context variants used by default
pip install numpy requests                            # the only Python deps
```

Models are configurable: `FORGE_GEN_MODEL`, `FORGE_JUDGE_MODEL`, `FORGE_EMBED_MODEL`, `OLLAMA_HOST`.

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

## Retrieval threshold note

`nomic-embed-text` compresses cosine scores: on the smoke corpus, off-topic questions scored 0.40-0.55
and on-topic ones 0.70+. A fixed threshold is fragile, so Phase 2 calibrates `min_score` per corpus from
off-topic probe questions instead of guessing.

## Tests

```
python tests/test_phase1.py    # offline: fake embeddings, stubbed LLM; no Ollama needed
python tests/smoke_live.py     # live run against Ollama
```

The offline suite (18 tests) was mutation-checked: each of 17 guards (tool gate, citation filter, CSV
path confinement, deterministic refusal, tag mapping, call de-duplication, loop termination, tool-free
stage 1, PDF header/footer filter, actionable Ollama errors, exponent cap, ...) was broken in turn and
the suite failed every time.

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
