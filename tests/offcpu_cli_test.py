#!/usr/bin/env python3
"""aura-perf offcpu: one value line, no stack text, explicit permission gate."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"


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
    return subprocess.run([str(BIN), "offcpu", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake(tmp, body):
    p = Path(tmp) / ("bt-" + str(len(list(Path(tmp).iterdir()))))
    p.write_text("#!/bin/sh" + chr(10) + body + chr(10))
    p.chmod(0o755)
    return p


def main():
    aura = resolve_aura()
    if not aura:
        print("skip offcpu_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-offcpu-"))
    fixture = tmp / "offcpu.txt"
    fixture.write_text("noise\noffcpu pid=123 total-ms=12 max-ms=5 samples=3\n")
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok offcpu:", name)
        else:
            print("FAIL offcpu:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(fixture)])
    check("file mode parses the summary", "offcpuctx tool=file" in r.stdout
          and "offcpu pid=123 total-ms=12" in r.stdout, r.stdout + r.stderr)
    check("file mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    r = run(dict(base, BPFTRACE_BIN="none"), ["--pid", "123", "--seconds", "1"])
    check("no bpftrace is explicit", "offcpu unavailable reason=no-bpftrace" in r.stdout,
          r.stdout + r.stderr)
    check("no bpftrace exits 3", r.returncode == 3, f"rc={r.returncode}")

    good = fake(tmp, 'echo "offcpu pid=123 total-ms=12 max-ms=5 samples=3"')
    r = run(dict(base, BPFTRACE_BIN=str(good)), ["--pid", "123", "--seconds", "1"])
    check("live mode parses the value", "offcpuctx tool=bpftrace" in r.stdout
          and "samples=3" in r.stdout, r.stdout + r.stderr)
    check("live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    denied = fake(tmp, 'echo "Permission denied" >&2; exit 1')
    r = run(dict(base, BPFTRACE_BIN=str(denied)), ["--pid", "123", "--seconds", "1"])
    check("permission is an ask", "offcpu blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
