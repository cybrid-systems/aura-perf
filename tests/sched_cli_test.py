#!/usr/bin/env python3
"""aura-perf sched: parsing and the permission gate.

File mode must turn perf sched latency text into schedtask values. Live
mode must say "no perf" instead of failing silently, and a permission
failure must be an ask line, not a traceback. A fake perf exercises the
record/latency path without needing PMU access.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
FIXTURE = """ Task | Runtime ms | Switches | Average delay ms | Maximum delay ms |
-----|------------|----------|-------------------|------------------|
 aura (123) | 12.500 | 4 | 0.250 | 1.500 |
 worker (456) | 3.000 | 2 | 0.100 | 0.400 |
"""


def resolve_aura():
    raw = os.environ.get("AURA_BIN", "aura")
    p = Path(raw)
    if p.is_file():
        return p
    found = shutil.which(raw)
    return Path(found) if found else None


def run(env, args):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([str(BIN), "sched", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake_perf(tmp, record_rc=0, latency=True):
    p = Path(tmp) / ("perf-" + str(record_rc) + ("-lat" if latency else ""))
    p.write_text("""#!/bin/sh
case "$1 $2" in
  "sched record")
    %s
    exit %d ;;
  "sched latency")
    cat %s
    exit 0 ;;
esac
exit 0
""" % ("echo 'perf: Permission denied' >&2" if record_rc else "true",
       record_rc, Path(tmp) / "latency.txt"))
    p.chmod(0o755)
    return p


def main():
    aura = resolve_aura()
    if not aura:
        print("skip sched_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-sched-"))
    lat = tmp / "latency.txt"
    lat.write_text(FIXTURE)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok sched:", name)
        else:
            print("FAIL sched:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(lat)])
    check("file mode parses tasks", "schedtrace tool=file" in r.stdout
          and "tasks=2" in r.stdout, r.stdout + r.stderr)
    check("file mode keeps the wakeup delay", "schedtask aura pid=123" in r.stdout
          and "max-delay-ms=1.5" in r.stdout, r.stdout)

    r = run(dict(base, PERF_BIN="none"), ["--", "true"])
    check("no perf is explicit", "sched unavailable reason=no-perf" in r.stdout,
          r.stdout + r.stderr)
    check("no perf exits 3", r.returncode == 3, f"rc={r.returncode}")

    denied = fake_perf(tmp, record_rc=1)
    r = run(dict(base, PERF_BIN=str(denied)), ["--", "true"])
    check("permission is an ask, not a crash",
          "sched blocked reason=permission" in r.stdout
          and "kernel.perf_event_paranoid=2" in r.stdout, r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    good = fake_perf(tmp, record_rc=0, latency=True)
    r = run(dict(base, PERF_BIN=str(good)), ["--", "true"])
    check("live mode parses the recorded latency",
          "schedtrace tool=perf" in r.stdout and "schedtask aura" in r.stdout,
          r.stdout + r.stderr)
    check("live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
