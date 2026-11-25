"""ForgeAI: brief + document folder -> working, tested agent.

    python forge.py --brief "I need an assistant that ..." --docs path/to/docs --out runs/my-agent
    python forge.py --brief brief.txt --docs docs/ --out runs/x --answers answers.json
    python forge.py --brief brief.txt --docs docs/ --out runs/x --auto     # unattended: defaults

Without --answers or --auto the requester is interviewed on the terminal (when stdin is a TTY).

Artifacts written to --out:
  inventory.json         what the factory found in the document folder
  interview.json         questions asked, answers, and which answers were assumed
  requirements.json/.md  the requirements document, including the groundability verdict per topic
  agent_def.json         the final agent (best kept iteration), loadable by `python -m runtime.runner`
  agent_def_iterN.json   the definition at each iteration
  generation_log.json    tool decisions and retrieval calibration, with token usage per stage
  evals.json             the generated test set (and cases dropped as unverifiable)
  results_iterN.json     per-case agent trace, judge verdict and failure category
  scorecard_iterN.json   aggregate scores, failure counts, judge self-test
  iteration_log.json     every change: what, why, which failures, score before/after, kept or reverted
  report.md              the honest report: what still fails and why, per-iteration scorecard
"""
import argparse
import json
import sys
import time
from pathlib import Path

from factory import evalgen, generator, groundability, intake, judge, optimizer, report
from factory.common import FACTORY_MODEL, log, write_json
from runtime import llm


def stage(name, usage_log, fn, *args):
    before, t0 = dict(llm.USAGE), time.time()
    result = fn(*args)
    usage_log[name] = {k: round(llm.USAGE[k] - before[k], 2) for k in llm.USAGE} | \
                      {"wall_seconds": round(time.time() - t0, 1)}
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brief", required=True, help="the brief text, or a path to a file containing it")
    ap.add_argument("--docs", required=True, help="document folder")
    ap.add_argument("--out", required=True, help="run folder for all artifacts")
    who = ap.add_mutually_exclusive_group()
    who.add_argument("--answers", help="JSON file of answers (list by position, or {question: answer})")
    who.add_argument("--auto", action="store_true", help="no requester: use each question's default assumption")
    who.add_argument("--questions-only", action="store_true",
                     help="print the clarifying questions and stop (decoding is deterministic, so a later run "
                          "asks the same ones; answer them with --answers)")
    a = ap.parse_args(argv)

    brief_path = Path(a.brief)
    brief = brief_path.read_text().strip() if brief_path.is_file() else a.brief.strip()
    docs, out = Path(a.docs), Path(a.out)
    if not docs.is_dir():
        print(f"error: document folder not found: {docs}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    usage = {}

    try:
        llm.preflight((llm.GEN_MODEL, FACTORY_MODEL, llm.EMBED_MODEL))

        log(f"intake: reading {docs}")
        inv = stage("inventory", usage, intake.inventory, docs)
        write_json(out / "inventory.json", inv)

        log("intake: drafting clarifying questions")
        qs = stage("questions", usage, intake.questions, brief, inv)
        if a.questions_only:
            write_json(out / "questions.json", qs)
            for i, q in enumerate(qs, 1):
                print(f"{i}. {q['question']}\n   default if unanswered: {q['default_assumption']}")
            return 0
        if a.answers:
            answer_fn = intake.file_answerer(json.loads(Path(a.answers).read_text()))
        elif a.auto or not sys.stdin.isatty():
            answer_fn = lambda q: None  # noqa: E731
            log(f"no requester attached: using default assumptions for {len(qs)} question(s)")
        else:
            print(f"\nForgeAI has {len(qs)} question(s) before it builds your assistant. "
                  "Press Enter to accept the default shown.")
            answer_fn = intake.cli_answerer
        clar = intake.interview(qs, answer_fn)
        write_json(out / "interview.json", {"questions": qs, "clarifications": clar})

        log("intake: writing requirements")
        req = stage("requirements", usage, intake.requirements, brief, inv, clar)

        index = generator.build_index(docs)
        off = generator.off_topic_scores(index)
        ceiling = max(off.values()) + generator.MARGIN
        req = stage("groundability", usage, groundability.guard, req, index, ceiling)
        write_json(out / "requirements.json", req)
        (out / "requirements.md").write_text(intake.render_markdown(req))
        log(f"groundability: {req['groundability']['summary']}")

        log("generator: building agent definition")
        definition = stage("generate", usage, generator.generate, req, inv, docs, out, index, off)
        write_json(out / "agent_def.json", definition)
        write_json(out / "generation_log.json", {
            "tool_decisions": definition["provenance"]["tool_decisions"],
            "calibration": definition["provenance"]["calibration"], "usage": usage})
        log(f"generated: tools={definition['tools'] or 'none'}  min_score={definition['retrieval']['min_score']}")

        log("evalgen: building the test set from the documents")
        evals = stage("evalgen", usage, evalgen.generate, req, definition, index, docs)
        write_json(out / "evals.json", evals)
        log(f"evalgen: {evals['total']} cases {evals['counts']}, {len(evals['dropped'])} dropped as unverifiable")

        selftest = stage("judge_selftest", usage, judge.judge_selftest, evals["cases"], index)
        best, final_results, history, changes, stop_reason = stage(
            "eval_and_optimize", usage, optimizer.loop, definition, out, index, evals["cases"], selftest,
            lambda name, obj: write_json(out / name, obj))
        write_json(out / "agent_def.json", best)  # the definition the runner should use: best kept iteration
        write_json(out / "iteration_log.json", {"history": history, "changes": changes, "stop_reason": stop_reason})
        write_json(out / "generation_log.json", {
            "tool_decisions": definition["provenance"]["tool_decisions"],
            "calibration": definition["provenance"]["calibration"], "usage": usage})
        (out / "report.md").write_text(report.build(req, best, evals, history, changes, final_results,
                                                    selftest, usage, stop_reason))
    except (llm.LLMError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    line = " -> ".join(f"{h['passed']}/{h['cases']}" + ("" if h["iteration"] == 0 or h.get("kept") else " (reverted)")
                       for h in history)
    log(f"scores by iteration: {line}; judge self-test {selftest['correct']}/{selftest['probes']}")
    log(f"report: {out / 'report.md'}")
    log(f"chat with it: python -m runtime.runner {out / 'agent_def.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
