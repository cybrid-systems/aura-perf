#!/usr/bin/env python3
"""aura-perf: a candidate that cannot typecheck never gets a worker.

The dry-run gate (mutate :check) reads the workspace, parses and typechecks
the candidate in call-local storage, and writes nothing. A candidate that
fails is a ROLLBACK in the parent: no job file, no process, no screen, no
held-out sample. The round still reports it as a decision.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base

TYPE_BAD = (
    '(hash "id" "type-bad" "target" "bench-kernel"\n'
    '                      "genome" "(define (bench-kernel xs) (undefined-thing xs))"\n'
    '                      "thought" "cannot typecheck; the dry-run gate must reject it")\n                '
)

GENES = ('"genes" (list (hash "id" "gene-type-gate" "ratio" 2 "actionable-ms" 1\n'
         '                                "per-round" 1\n'
         '                                "order" (list "type-bad")))')


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-type-gate-"))
    base.write_project(tmp, genes=GENES)
    spec = tmp / "perf" / "spec.aura"
    text = spec.read_text()
    marker = '(hash "id" "specialize-k-ref"'
    if marker not in text:
        print("FAIL type_gate_round_test: spec template changed")
        return 1
    spec.write_text(text.replace(marker, TYPE_BAD + marker, 1))

    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    decisions = [ln for ln in lines if ln.startswith(("round", "candidate", "type-gate", "verdict", "kernel"))]

    check.that("type-gate: the round planned the bad candidate",
               "round 1 candidates type-bad" in lines, str(decisions))
    check.line("type-gate: it is a ROLLBACK, not a trial",
               report, "candidate type-bad ROLLBACK reason=type-gate")
    check.that("type-gate: the diagnostic is on its own line",
               any(ln.startswith("type-gate type-bad type-error") for ln in lines), str(decisions))
    check.that("type-gate: no job was written for it",
               not (tmp / "out" / "jobs" / "type-bad.job.json").exists(), str(decisions))
    check.that("type-gate: no candidate result was invented",
               not any("candidate type-bad PASS" in ln for ln in lines), str(decisions))
    check.that("type-gate: intend was not met, exit non-zero",
               run.returncode != 0 and lines[:1] and lines[0].startswith("verdict intend-met=0"),
               f"rc={run.returncode} {lines[:1]}")

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
