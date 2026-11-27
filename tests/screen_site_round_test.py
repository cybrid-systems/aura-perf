#!/usr/bin/env python3
"""aura-perf: the cheap screen reads the candidate's site, not the kernel.

The slow candidate below returns the right value but walks the list 200
extra times. Its site time is far above the base, so the screen prunes it
without a held-out sample. The candidate line carries both site numbers;
the whole-kernel number is only the fallback when the tree has no site.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base

GENES = ('"genes" (list (hash "id" "gene-screen-site" "ratio" 2 "actionable-ms" 1\n'
         '                                "per-round" 1\n'
         '                                "order" (list "slow-ref")))')

SLOW = (
    "(define (k-ref xs i)\n"
    "  (let loop ((k 0) (v (list-ref xs i)))\n"
    "    (if (>= k 200)\n"
    "        v\n"
    "        (begin (list-ref xs i) (loop (+ k 1) v)))))"
)


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-screen-site-"))
    base.write_project(tmp, genes=GENES)
    spec = tmp / "perf" / "spec.aura"
    text = spec.read_text()
    text = text.replace('"protected" (list "k-ref" "k-length")', '"protected" (list)')
    marker = '(hash "id" "specialize-k-ref"'
    entry = ('(hash "id" "slow-ref" "target" "k-ref" "genome" %s\n'
             '                      "thought" "correct but 200x the site work")\n                ') % json.dumps(SLOW)
    if marker not in text:
        print("FAIL screen_site_round_test: spec template changed")
        return 1
    spec.write_text(text.replace(marker, entry + marker, 1))

    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    decisions = [ln for ln in lines if ln.startswith(("round", "candidate", "kernel", "verdict"))]

    check.that("screen-site: the round planned the slow candidate",
               "round 1 candidates slow-ref" in lines, str(decisions))
    check.line("screen-site: the site screen pruned it",
               report, "candidate slow-ref ROLLBACK reason=screen-pruned")
    line = next((ln for ln in lines if ln.startswith("candidate slow-ref ")), "")
    check.that("screen-site: both site numbers are on the candidate line",
               "screen-site-ms=" in line and "screen-base-site-ms=" in line, line)
    check.that("screen-site: no held-out sample was spent",
               "heldout-ms=-1" in line, line)
    check.that("screen-site: the slow candidate was not kept",
               not any(ln.startswith("kernel KEEP id=slow-ref") for ln in lines), str(decisions))

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
