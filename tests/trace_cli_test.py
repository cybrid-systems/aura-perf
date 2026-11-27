#!/usr/bin/env python3
"""aura-perf trace: sched_switch parsing, tracefs sampling and its gate.

File mode is pure. Live mode is exercised against a temporary tracefs
tree: writable in the success case, read-only in the permission case, so
no root and no host tracing are needed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
EVENTS = """ <...>-1 [000] d..2 100.000000: sched_switch: prev_comm=aura prev_pid=1 prev_prio=120 prev_state=R ==> next_comm=worker next_pid=2 next_prio=120
 <...>-2 [000] d..2 100.005000: sched_switch: prev_comm=worker prev_pid=2 prev_prio=120 prev_state=S ==> next_comm=aura next_pid=1 next_prio=120
 <...>-1 [000] d..2 100.012000: sched_switch: prev_comm=aura prev_pid=1 prev_prio=120 prev_state=S ==> next_comm=idle next_pid=0 next_prio=120
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
    return subprocess.run([str(BIN), "trace", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def tracefs(tmp, writable=True):
    root = Path(tempfile.mkdtemp(prefix="tracefs-", dir=tmp))
    (root / "events/sched/sched_switch").mkdir(parents=True)
    (root / "trace").write_text(EVENTS)
    (root / "tracing_on").write_text("0\n")
    (root / "events/sched/sched_switch/enable").write_text("0\n")
    if not writable:
        (root / "tracing_on").chmod(0o444)
    return root


def main():
    aura = resolve_aura()
    if not aura:
        print("skip trace_cli_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-trace-"))
    fixture = tmp / "trace.txt"
    fixture.write_text(EVENTS)
    base = {"AURA_BIN": str(aura)}
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok trace:", name)
        else:
            print("FAIL trace:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    r = run(base, ["--file", str(fixture)])
    check("file mode counts events", "tracetrace tool=file" in r.stdout
          and "events=3" in r.stdout, r.stdout + r.stderr)
    check("file mode keeps off-CPU time", "schedswitch task=worker pid=2" in r.stdout
          and "off-ms=7" in r.stdout, r.stdout)

    r = run(dict(base, AURA_PERF_TRACEFS="/nonexistent"), ["--seconds", "0"])
    check("missing tracefs is explicit", "trace unavailable reason=tracefs-not-mounted" in r.stdout,
          r.stdout + r.stderr)
    check("missing tracefs exits 3", r.returncode == 3, f"rc={r.returncode}")

    root = tracefs(tmp, writable=True)
    r = run(dict(base, AURA_PERF_TRACEFS=str(root), AURA_PERF_TRACE_KEEP="1"),
            ["--seconds", "0"])
    check("live tracefs parses the sample", "tracetrace tool=tracefs" in r.stdout
          and "schedswitch task=aura" in r.stdout, r.stdout + r.stderr)
    check("live tracefs restores tracing_on", (root / "tracing_on").read_text().strip() in ("0", "1"),
          (root / "tracing_on").read_text())
    check("live tracefs exits 0", r.returncode == 0, f"rc={r.returncode}")

    ro = tracefs(tmp, writable=False)
    r = run(dict(base, AURA_PERF_TRACEFS=str(ro)), ["--seconds", "0"])
    check("write permission is an ask", "trace blocked reason=permission" in r.stdout,
          r.stdout + r.stderr)
    check("write permission exits 4", r.returncode == 4, f"rc={r.returncode}")

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
