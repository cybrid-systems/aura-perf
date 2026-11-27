#!/usr/bin/env python3
"""aura-perf mem: sampled symbols and overhead, with an explicit gate."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
REPORT = """# Samples: 12K of event 'cpu/mem-loads,ldlat=30/P'
# Overhead  Samples  Symbol
# ........  .......  ......
    12.34%     1234  foo
     5.00%      500  [.] bar
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
    return subprocess.run([str(BIN), "mem", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake(tmp, record_ok=True):
    p = Path(tmp) / ("perf-" + str(len(list(Path(tmp).iterdir()))))
    p.write_text("""#!/bin/sh
if [ "$1 $2" = "mem record" ]; then
  %s
fi
if [ "$1 $2" = "mem report" ]; then
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
        print("skip mem_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-mem-"))
    fixture = tmp / "report.txt"
    fixture.write_text(REPORT)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok mem:", name)
        else:
            print("FAIL mem:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(fixture)])
    check("file mode parses samples and symbols", "memtool tool=file" in r.stdout
          and "memsym foo samples=1234" in r.stdout, r.stdout + r.stderr)
    check("file mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    r = run(dict(base, PERF_BIN="none"), ["--", "true"])
    check("no perf is explicit", "mem unavailable reason=no-perf" in r.stdout,
          r.stdout + r.stderr)
    check("no perf exits 3", r.returncode == 3, f"rc={r.returncode}")

    good = fake(tmp, True)
    r = run(dict(base, PERF_BIN=str(good)), ["--", "true"])
    check("live mode parses the report", "memtool tool=perf" in r.stdout
          and "samples=12000" in r.stdout, r.stdout + r.stderr)
    check("live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    denied = fake(tmp, False)
    r = run(dict(base, PERF_BIN=str(denied)), ["--", "true"])
    check("permission is an ask", "mem blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
