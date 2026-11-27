#!/usr/bin/env python3
"""aura-perf c2c: cache-line contention summary and its permission gate."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
REPORT = """=================================================
            Trace Event Information
=================================================
  Total records                     :      1,234
  Loads                             :      1,000
  Stores                            :        234
  LLC hits                          :        900
  Local RAM hits                    :        200
  Remote HITM                       :         34
  Remote DRAM                       :         10
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
    return subprocess.run([str(BIN), "c2c", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake(tmp, record_ok=True):
    p = Path(tmp) / ("perf-" + str(len(list(Path(tmp).iterdir()))))
    p.write_text("""#!/bin/sh
if [ "$1 $2" = "c2c record" ]; then
  %s
fi
if [ "$1 $2" = "c2c report" ]; then
  cat %s
  exit 0
fi
exit 0
""" % ("true; exit 0" if record_ok else "echo 'perf: Permission denied' >&2; exit 1",
       Path(tmp) / "report.txt"))
    p.chmod(0o755)
    return p


def main():
    aura = resolve_aura()
    if not aura:
        print("skip c2c_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-c2c-"))
    fixture = tmp / "report.txt"
    fixture.write_text(REPORT)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok c2c:", name)
        else:
            print("FAIL c2c:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(fixture)])
    check("file mode parses the summary", "c2ctrace tool=file" in r.stdout
          and "remote-hitm=34" in r.stdout, r.stdout + r.stderr)
    check("file mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    r = run(dict(base, PERF_BIN="none"), ["--", "true"])
    check("no perf is explicit", "c2c unavailable reason=no-perf" in r.stdout,
          r.stdout + r.stderr)
    check("no perf exits 3", r.returncode == 3, f"rc={r.returncode}")

    good = fake(tmp, True)
    r = run(dict(base, PERF_BIN=str(good)), ["--", "true"])
    check("live mode parses the report", "c2ctrace tool=perf" in r.stdout
          and "total-records=1234" in r.stdout, r.stdout + r.stderr)
    check("live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    denied = fake(tmp, False)
    r = run(dict(base, PERF_BIN=str(denied)), ["--", "true"])
    check("permission is an ask", "c2c blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
