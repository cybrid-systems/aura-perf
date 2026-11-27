#!/usr/bin/env python3
"""aura-perf runqlat/biolatency: bcc histograms as values and gates."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
HIST = """     usecs               : count     distribution
         0 -> 1          : 0        |                                        |
         2 -> 3          : 5        |*****                                   |
         4 -> 7          : 3        |***                                     |
"""


def resolve_aura():
    raw = os.environ.get("AURA_BIN", "aura")
    p = Path(raw)
    if p.is_file():
        return p
    found = shutil.which(raw)
    return Path(found) if found else None


def run(env, tool, args):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([str(BIN), tool, *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def fake(tmp, name, ok=True):
    p = Path(tmp) / (name + "-" + str(len(list(Path(tmp).iterdir()))))
    p.write_text("#!/bin/sh\n" + ("" if ok else 'echo "Permission denied" >&2; exit 1') + "\ncat " + str(Path(tmp) / "hist.txt") + "\n")
    p.chmod(0o755)
    return p


def main():
    aura = resolve_aura()
    if not aura:
        print("skip bcchist_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-bcchist-"))
    fixture = tmp / "hist.txt"
    fixture.write_text(HIST)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok bcchist:", name)
        else:
            print("FAIL bcchist:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    for tool, envname in (("runqlat", "RUNQLAT_BIN"), ("biolatency", "BIOLATENCY_BIN")):
        r = run(base, tool, ["--file", str(fixture)])
        check(tool + " file mode parses buckets", "histtool tool=file" in r.stdout
              and "total=8" in r.stdout and "bucket=2-3 count=5" in r.stdout,
              r.stdout + r.stderr)
        check(tool + " file mode exits 0", r.returncode == 0, f"rc={r.returncode}")

        r = run(dict(base, **{envname: "none"}), tool, ["--seconds", "0"])
        check(tool + " no bcc is explicit", tool + " unavailable reason=no-bcc" in r.stdout,
              r.stdout + r.stderr)
        check(tool + " no bcc exits 3", r.returncode == 3, f"rc={r.returncode}")

        good = fake(tmp, tool, True)
        r = run(dict(base, **{envname: str(good)}), tool, ["--seconds", "0"])
        check(tool + " live mode parses buckets", "histtool tool=bcc" in r.stdout
              and "max=7" in r.stdout, r.stdout + r.stderr)
        check(tool + " live mode exits 0", r.returncode == 0, f"rc={r.returncode}")

    denied = fake(tmp, "denied", False)
    r = run(dict(base, RUNQLAT_BIN=str(denied)), "runqlat", ["--seconds", "0"])
    check("permission is an ask", "runqlat blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
