#!/usr/bin/env python3
"""aura-perf: scheduler and latency evidence ride on a real round.

The worker now reports per-candidate runqueue wait (schedstat) and the
held-out p50/p90/p99 distribution. Both are evidence, not gates: the
verdict is unchanged. schedstat is skipped when /proc/self/schedstat is
not readable on the host.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-methodology-"))
    base.write_project(tmp, genes="")
    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    candidates = [ln for ln in lines if ln.startswith("candidate linear-scan ")]
    latency = [ln for ln in lines if ln.startswith("latency linear-scan ")]
    sched = [ln for ln in lines if ln.startswith("sched linear-scan ")]

    check.that("methodology: the candidate line exists", bool(candidates), str(lines[-6:]))
    if candidates:
        line = candidates[0]
        check.that("methodology: p90 rides on the candidate line",
                   "heldout-p90-ms=" in line, line)
        check.that("methodology: the latency distribution is a separate line",
                   bool(latency) and "p50-ms=" in latency[0] and "p90-ms=" in latency[0]
                   and "p99-ms=" in latency[0] and "spread-ms=" in latency[0], str(latency))
    if os.path.exists("/proc/self/schedstat"):
        check.that("methodology: scheduler wait is measured without root",
                   bool(sched) and "wait-ms=" in sched[0] and "wait-pct=" in sched[0]
                   and "vol=" in sched[0] and "invol=" in sched[0], str(sched))
        check.that("methodology: the candidate line carries scheduler wait",
                   "sched-wait-ms=" in candidates[0], candidates[0])
    else:
        check.that("methodology: schedstat absent is explicit, not zero",
                   "sched-wait-ms=" not in candidates[0], candidates[0])

    check.that("methodology: the verdict is unchanged",
               run.returncode == 0 and lines[:1] and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
