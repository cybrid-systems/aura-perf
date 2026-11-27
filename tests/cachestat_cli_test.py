#!/usr/bin/env python3
"""aura-perf cachestat: bcc page-cache summary with an explicit gate."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
REPORT = """    HITS   MISSES  DIRTIES HITRATIO   BUFFERS_MB  CACHED_MB
    1234        5        0   99.60%          100        900
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
    return subprocess.run([str(BIN), "cachestat", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake(tmp, ok=True):
    p = Path(tmp) / ("cs-" + str(len(list(Path(tmp).iterdir()))))
    p.write_text("#!/bin/sh\n" + ("" if ok else 'echo "Permission denied" >&2; exit 1') + "\ncat " + str(Path(tmp) / "report.txt") + "\n")
    p.chmod(0o755)
    return p


def main():
    aura = resolve_aura()
    if not aura:
        print("skip cachestat_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-cachestat-"))
    fixture = tmp / "report.txt"
    fixture.write_text(REPORT)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok cachestat:", name)
        else:
            print("FAIL cachestat:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(fixture)])
    check("file mode parses the row", "cachestattool tool=file" in r.stdout
          and "hitratio-pct=99.6" in r.stdout, r.stdout + r.stderr)
    check("file mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    r = run(dict(base, CACHESTAT_BIN="none"), ["--seconds", "0"])
    check("no bcc is explicit", "cachestat unavailable reason=no-bcc" in r.stdout,
          r.stdout + r.stderr)
    check("no bcc exits 3", r.returncode == 3, f"rc={r.returncode}")

    good = fake(tmp, True)
    r = run(dict(base, CACHESTAT_BIN=str(good)), ["--seconds", "0"])
    check("live mode parses the row", "cachestattool tool=bcc" in r.stdout
          and "hits=1234" in r.stdout, r.stdout + r.stderr)
    check("live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    denied = fake(tmp, False)
    r = run(dict(base, CACHESTAT_BIN=str(denied)), ["--seconds", "0"])
    check("permission is an ask", "cachestat blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
