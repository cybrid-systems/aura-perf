#!/usr/bin/env python3
"""aura-perf: a site's headroom is measured before the budget is spent.

A headroom job is not a candidate. It replaces one site with a cheap stub
in its own worldline, runs the kernel once, restores the binding, and
reports the difference from a fresh baseline child. The report names the
upper bound; a stub that breaks the kernel is unavailable, not 0 ms.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-headroom-"))
    base.write_project(tmp, genes="")
    spec = tmp / "perf" / "spec.aura"
    spec.write_text(spec.read_text().replace('"protected" (list "k-ref" "k-length")',
                                             '"protected" (list)'))

    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    heads = [ln for ln in lines if ln.startswith("site-headroom")]
    candidates = [ln for ln in lines if ln.startswith("candidate ")]

    check.that("headroom: both hot sites were probed",
               any(ln.startswith("site-headroom k-ref base-ms=") for ln in lines)
               and any(ln.startswith("site-headroom k-length base-ms=") for ln in lines),
               str(heads))
    check.that("headroom: a probed site carries a percentage",
               all("headroom-pct=" in ln for ln in heads if not ln.startswith("site-headroom-unavailable")),
               str(heads))
    check.that("headroom: the candidate line carries its site's upper bound",
               any(ln.startswith("candidate specialize-k-ref ") and "headroom-pct=" in ln
                   for ln in lines), str(candidates))
    check.that("headroom: no probe was reported unavailable",
               not any(ln.startswith("site-headroom-unavailable") for ln in lines), str(heads))
    check.that("headroom: profiles come before the first round",
               lines.index(heads[0]) < next((i for i, ln in enumerate(lines)
                                             if ln.startswith("round 1 candidates")), 10**9)
               if heads else False)
    check.that("headroom: the round still met its intend",
               run.returncode == 0 and lines[:1] and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
