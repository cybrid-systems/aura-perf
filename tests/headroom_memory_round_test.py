#!/usr/bin/env python3
"""aura-perf: a site with no headroom is remembered across runs.

First run probes both sites and forgets them (the test asks for a 101%
floor). Second run reads memory.json, names the remembered sites, and
starts no headroom probe child for them.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import llm_proposer_test as base


def main():
    check = base.Check()
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-headmem-"))
    base.write_project(tmp, genes="")
    spec = tmp / "perf" / "spec.aura"
    text = spec.read_text()
    text = text.replace('"protected" (list "k-ref" "k-length")', '"protected" (list)')
    text = text.replace('"min-faster-pct" 10 "checksum" #t',
                        '"min-faster-pct" 10 "headroom-forget-pct" 101 "checksum" #t')
    spec.write_text(text)

    base.run_round(tmp)
    first = (tmp / "out" / "report.txt").read_text()
    check.that("headmem: first run forgets the low sites",
               "headroom-forget k-ref" in first and "headroom-forget k-length" in first,
               first[-400:])
    memory = (tmp / "out" / "memory.json").read_text() if (tmp / "out" / "memory.json").is_file() else ""
    check.that("headmem: the record is persisted",
               '"headroom-no-room"' in memory, memory[:400])

    base.run_round(tmp)
    second = (tmp / "out" / "report.txt").read_text()
    check.that("headmem: second run names the remembered sites",
               "headroom-remembered k-ref" in second and "headroom-remembered k-length" in second,
               second[-400:])
    check.that("headmem: second run starts no site probe",
               "site-headroom k-ref" not in second and "site-headroom k-length" not in second,
               second[-400:])

    shutil.rmtree(tmp, ignore_errors=True)
    return check.fail


if __name__ == "__main__":
    sys.exit(main())
