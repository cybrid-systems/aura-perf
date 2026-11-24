#!/usr/bin/env python3
"""aura-perf: a fresh round whose first candidates fail.

Aura #5255 on, std/evo-core ends a trial that violated a hard constraint
"infeasible". Read as a trial that did not finish, it stopped the round
at "strategy ROLLBACK reason=trial-infrastructure" and no kernel was
kept: on a fresh checkout the example could not meet its intend.

This is the example's own flow on a fresh project, with no model
proposer: the first round trials wrong-scale (its checksum does not
match) and redundant-pass (slower), the round after it trials
linear-scan, and the gate KEEPs linear-scan.

Reuses the project of tests/llm_proposer_test.py.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-checksum-"))
    # No genes: the seed's own strategy orders the catalog, two a round.
    base.write_project(tmp, genes="")
    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    decisions = [ln for ln in lines if ln.startswith(("round", "candidate", "strategy", "kernel", "verdict"))]

    check.that("checksum: nothing was remembered before this round",
               "memory-loaded 0 path=out/memory.json" in lines)
    check.that("checksum: the first round trials the two that fail",
               "round 1 candidates wrong-scale,redundant-pass" in lines, str(decisions))
    check.line("checksum: a trial that failed its constraint is the candidate's ROLLBACK",
               report, "candidate wrong-scale ROLLBACK reason=checksum mismatches=4")
    # The conclusion is "the slower candidate is rolled back", not the
    # reason: a single cheap screen reading can miss the 2x prune on a
    # noisy machine, and the held-out measurement then rolls it back as
    # no-speedup. Both reasons refuse the candidate; neither KEEPs it.
    rollback = next((ln for ln in lines
                     if ln.startswith("candidate redundant-pass ROLLBACK reason=")), "")
    reason = rollback.split("reason=", 1)[-1].split(" ", 1)[0]
    check.that("checksum: the slower one is rolled back too",
               reason in ("screen-pruned", "no-speedup"),
               str(decisions))
    check.that("checksum: neither is the round's infrastructure failing",
               not any(ln.startswith("strategy ROLLBACK reason=trial-infrastructure") for ln in lines),
               str(decisions))
    check.that("checksum: the round went on to linear-scan",
               "round 2 candidates linear-scan" in lines, str(decisions))
    check.that("checksum: the gate KEPT linear-scan",
               any(ln.startswith("kernel KEEP id=linear-scan") for ln in lines), str(decisions))
    check.that("checksum: intend met, exit 0",
               run.returncode == 0 and lines[:1] and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")
    check.line("checksum: no model proposer was wired", report, "llm-proposer no-provider")

    memory = (tmp / "out" / "memory.json").read_text()
    check.that("checksum: the failed ideas are remembered for the next run",
               '"idea":"wrong-scale"' in memory and '"idea":"redundant-pass"' in memory, memory)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(check.fail)


if __name__ == "__main__":
    main()
