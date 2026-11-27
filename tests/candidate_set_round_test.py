#!/usr/bin/env python3
"""aura-perf: one candidate may rewrite several defines at once.

A set is one worldline: every mutation is rebound, then one eval-current.
The base is measured with every target rebound to its own body, so the
set and its reference pay the same rebind tax. The site floor sums the
set's sites; a site the candidate stops calling is 0 in the candidate
tree, not a missing measurement.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base

GENES = ('"genes" (list (hash "id" "gene-set" "ratio" 2 "actionable-ms" 1\n'
         '                                "per-round" 1\n'
         '                                "order" (list "set-pass")))')

SET_ENTRY = (
    '(hash "id" "set-pass" "genomes"\n'
    '                      (list (hash "target" "bench-kernel" "genome" %s)\n'
    '                            (hash "target" "k-ref" "genome" "(define (k-ref xs i) (list-ref xs i))"))\n'
    '                      "thought" "two sites at once")\n                '
)


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-set-"))
    base.write_project(tmp, genes=GENES)
    spec = tmp / "perf" / "spec.aura"
    text = spec.read_text()
    text = text.replace('"protected" (list "k-ref" "k-length")', '"protected" (list)')
    text = text.replace('"min-faster-pct" 10 "checksum" #t "budget" 4',
                        '"min-faster-pct" 10 "site-min-faster-pct" 5 "checksum" #t "budget" 4')
    marker = '(hash "id" "specialize-k-ref"'
    if marker not in text:
        print("FAIL candidate_set_round_test: spec template changed")
        return 1
    linear = json.dumps((base.ROOT / "examples/sum-scan/candidates/linear-scan.aura").read_text().rstrip("\n"))
    spec.write_text(text.replace(marker, (SET_ENTRY % linear) + marker, 1))

    run = base.run_round(tmp)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    decisions = [ln for ln in lines if ln.startswith(("round", "candidate", "site ", "kernel", "verdict"))]

    check.that("set: the round planned the set",
               "round 1 candidates set-pass" in lines, str(decisions))
    check.line("set: it passed the same gate as a single candidate",
               report, "candidate set-pass PASS reason=gate-pass")
    check.that("set: the report names both reference targets",
               any(ln.startswith("candidate set-pass ") and "ref-target=bench-kernel+k-ref" in ln
                   for ln in lines), str(decisions))
    check.that("set: the site floor sums both sites",
               any(ln.startswith("site bench-kernel+k-ref base-ms=") and "cand-ms=" in ln
                   for ln in lines), str(decisions))
    check.that("set: the gate KEPT the set",
               any(ln.startswith("kernel KEEP id=set-pass") for ln in lines), str(decisions))
    check.that("set: intend met, exit 0",
               run.returncode == 0 and lines[:1] and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
