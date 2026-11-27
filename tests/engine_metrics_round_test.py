#!/usr/bin/env python3
"""aura-perf: every trial carries its engine cost as evidence.

The worker snapshots compile/mutate/jit/arena groups before and after the
trial and writes the delta into the result. The report line is the answer
to "the candidate was fast, but did it cause a rebuild?".
"""
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-engine-"))
    base.write_project(tmp, genes="")
    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    engines = [ln for ln in lines if ln.startswith("trial-engine ")]
    candidates = [ln for ln in lines if ln.startswith("candidate ")]
    splits = [ln for ln in lines if ln.startswith("split ")]

    check.that("engine: the trial line exists", len(engines) >= 1, str(candidates))
    if engines:
        line = engines[0]
        check.that("engine: the counters are named",
                   all(k in line for k in ("rebuild=", "cascade-full=", "body-only=",
                                           "relower-full=", "mutate-batches=",
                                           "jit-compilations=", "jit-deopt=",
                                           "arena-compacts=")), line)
        check.that("engine: the candidate line carries the rebuild bit",
                   any("rebuild=" in ln for ln in candidates), str(candidates))
        check.that("engine: the time split is a separate line",
                   any(ln.startswith("split linear-scan ")
                       and "raw-ms=" in ln and "null-ms=" in ln and "cand-ms=" in ln
                       and "mutation-effect-ms=" in ln and "rebind-tax-ms=" in ln
                       for ln in splits), str(splits))
        check.that("engine: the candidate line carries the mutation effect",
                   any("mutation-effect-ms=" in ln for ln in candidates), str(candidates))
    check.that("engine: the round still met its intend",
               run.returncode == 0 and lines[:1] and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
