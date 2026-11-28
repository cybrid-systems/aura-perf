#!/usr/bin/env python3
"""aura-perf profile launch-mode: a workload that exits non-zero before
the window ends still gets its report (aura-perf#35). perf record
propagates the command's exit code; the samples on disk are the
evidence. A fake perf keeps this hermetic: no PMU, no permissions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "aura-perf"
REPORT = """# Overhead  Symbol
# ........  ....................
#
    62.30%  [.] work
    37.70%  [.] main
"""


def fake_perf(tmp, mode):
    p = Path(tmp) / ("perf-" + mode)
    p.write_text("""#!/bin/sh
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out=$a; fi
  prev=$a
done
case "$1" in
  record)
    if [ "%s" = "nodata" ]; then
      echo "perf: Permission denied" >&2
      exit 1
    fi
    printf 'fake perf data\\n' > "$out"
    echo "[ perf record: Captured and wrote 0.025 MB $out (623 samples) ]" >&2
    exit %s
    ;;
  report)
    cat <<'EOF'
%s
EOF
    exit 0
    ;;
esac
exit 0
""" % (mode, "3" if mode == "workload" else "0", REPORT))
    p.chmod(0o755)
    return p


def run(env, args):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([str(BIN), "profile", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=60)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-profile-"))
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok profile:", name)
        else:
            print("FAIL profile:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    # The workload exits 3 before the window ends; perf already wrote
    # samples. The report and JSON must exist and carry workload_exit=3.
    out = tmp / "out-workload"
    r = run({"PERF_BIN": str(fake_perf(tmp, "workload"))},
            ["--seconds", "5", "--out", str(out), "--", "true"])
    check("workload exit keeps the report", r.returncode == 0
          and (out / "profile.txt").is_file() and (out / "profile.json").is_file(),
          r.stdout + r.stderr)
    check("exit is a note, not a failure",
          "workload exited rc=3" in r.stderr and "perf record failed" not in r.stderr,
          r.stdout + r.stderr)
    if (out / "profile.json").is_file():
        doc = json.loads((out / "profile.json").read_text())
        check("json carries workload_exit", doc.get("workload_exit") == 3
              and doc.get("kind") == "native-profile", json.dumps(doc))
    if (out / "profile.txt").is_file():
        check("text carries workload-exit",
              "workload-exit: 3" in (out / "profile.txt").read_text(),
              (out / "profile.txt").read_text())

    # A clean exit (or the window's own timeout) keeps the old shape:
    # no workload-exit line, workload_exit null.
    out = tmp / "out-clean"
    r = run({"PERF_BIN": str(fake_perf(tmp, "clean"))},
            ["--seconds", "5", "--out", str(out), "--", "true"])
    check("clean exit still reports", r.returncode == 0
          and (out / "profile.json").is_file(), r.stdout + r.stderr)
    if (out / "profile.json").is_file():
        doc = json.loads((out / "profile.json").read_text())
        check("clean exit has no workload_exit", doc.get("workload_exit") is None,
              json.dumps(doc))

    # perf itself failed and produced no data: still fatal, with the
    # record log as evidence.
    out = tmp / "out-nodata"
    r = run({"PERF_BIN": str(fake_perf(tmp, "nodata"))},
            ["--seconds", "5", "--out", str(out), "--", "true"])
    check("no samples is fatal", r.returncode == 1
          and "perf produced no samples" in r.stderr
          and not (out / "profile.json").exists(), r.stdout + r.stderr)

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
