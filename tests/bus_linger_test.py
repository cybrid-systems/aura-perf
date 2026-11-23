#!/usr/bin/env python3
"""aura-perf#28: the bus host must outlive the round for a linger window.

A witness peer attaches DURING the window and reads the round's committed
evidence; stdin EOF ends the window early and unhosts;
AURA_PERF_BUS_LINGER_S=0 exits right after the report (the pre-#28
behavior, kept as the opt-out). Needs a bus-capable Aura (std/bus +
bus:host) via AURA_BIN; skipped otherwise.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AURA = os.environ.get("AURA_BIN", "aura")
WS = 993

WITNESS = """(require "std/bus" all:)
(define s (bus:attach "" 993 2 1 255))
(if (not (bus:ok? s))
    (begin (display "WITNESS-ATTACH-FAIL") (newline))
    (let ((sid (car (cdr s))))
      (let ((q (bus:query sid 1 0 0)))
        (display (if (and (bus:ok? q)
                          (let loop ((rows (list-ref q 4)))
                            (cond ((null? rows) #f)
                                  ((and (pair? (car rows)) (= 900001 (car (car rows)))) #t)
                                  (else (loop (cdr rows))))))
                     "WITNESS-METRIC-OK" "WITNESS-METRIC-FAIL")) (newline))
      (let ((a (bus:audit sid 0)))
        (display (if (and (bus:ok? a) (> (car (cdr a)) 0))
                     "WITNESS-AUDIT-OK" "WITNESS-AUDIT-FAIL")) (newline))
      (bus:detach sid)))
"""


def skip(msg):
    print(f"skip bus_linger_test: {msg}")
    sys.exit(0)


def main():
    aura = Path(AURA)
    if not aura.is_file():
        from shutil import which
        resolved = which(AURA)
        if not resolved:
            skip("no aura binary")
        aura = Path(resolved)
    lib = aura.resolve().parent.parent / "lib"
    if not (lib / "std" / "bus.aura").is_file():
        skip(f"{aura} has no std/bus")

    fail = 0
    rt = tempfile.mkdtemp(prefix="aura-perf-linger-")
    sock = Path(rt) / "aura" / "bus" / f"{WS}.sock"
    env = dict(os.environ, XDG_RUNTIME_DIR=rt, AURA_PERF_BUS_WORKSPACE=str(WS),
               AURA_SANDBOX="off", AURA_BIN=str(aura))
    witness = Path(rt) / "witness.aura"
    witness.write_text(WITNESS)

    # --- 1. linger window: witness attaches while the round serves -------
    env["AURA_PERF_BUS_LINGER_S"] = "30"
    out = open(Path(rt) / "round.out", "w")
    # sleep holds the round's stdin open; killing it is the EOF signal.
    sleeper = subprocess.Popen(["sleep", "300"], stdout=subprocess.PIPE)
    roundp = subprocess.Popen(["./run.sh", "autotune"], cwd=ROOT, stdin=sleeper.stdout,
                              stdout=out, stderr=subprocess.STDOUT, env=env)
    sleeper.stdout.close()
    try:
        ready = False
        for _ in range(600):  # up to 60s for the round to reach the window
            if sock.exists() and "verdict intend-met=" in (Path(rt) / "round.out").read_text():
                ready = True
                break
            if roundp.poll() is not None:
                break
            time.sleep(0.1)
        if not ready:
            print("FAIL linger: round never reached the serve window")
            print((Path(rt) / "round.out").read_text()[-800:])
            fail = 1
        else:
            w = subprocess.run([str(aura), "--quiet", str(witness)], capture_output=True,
                               text=True, env=env, timeout=30)
            if "WITNESS-METRIC-OK" in w.stdout and "WITNESS-AUDIT-OK" in w.stdout:
                print("ok linger: witness read the round's committed evidence during the window")
            else:
                print("FAIL linger: witness could not read the round's evidence")
                print(w.stdout, w.stderr[:300])
                fail = 1
            # EOF on stdin ends the window early; the round unhosts and exits.
            sleeper.kill()
            try:
                rc = roundp.wait(timeout=15)
                text = (Path(rt) / "round.out").read_text()
                # The autotune verdict is not part of this test: the round
                # may exit 1 when the example misses its intend. What matters
                # is that stdin EOF closed the host cleanly.
                if rc in (0, 1) and "bus host closed" in text and not sock.exists():
                    print("ok linger: stdin EOF ended the window, unhosted, exit 0")
                else:
                    print(f"FAIL linger: unclean window end rc={rc} socket={sock.exists()}")
                    print(text[-400:])
                    fail = 1
            except subprocess.TimeoutExpired:
                print("FAIL linger: round did not exit after stdin EOF")
                fail = 1
    finally:
        sleeper.kill()
        if roundp.poll() is None:
            roundp.kill()
            roundp.wait()
        out.close()

    # --- 2. opt-out: linger 0 exits right after the report ---------------
    env["AURA_PERF_BUS_LINGER_S"] = "0"
    r = subprocess.run(["./run.sh", "autotune"], cwd=ROOT, capture_output=True, text=True,
                       env=env, stdin=subprocess.DEVNULL, timeout=120)
    if "verdict intend-met=" in r.stdout and "linger 0s" in r.stdout and not sock.exists():
        print("ok linger-0: round exited after the report, no serve window")
    else:
        print("FAIL linger-0: expected immediate exit with the report written")
        print(r.stdout[-400:], r.stderr[:300])
        fail = 1

    import shutil
    shutil.rmtree(rt, ignore_errors=True)
    sys.exit(fail)


if __name__ == "__main__":
    main()
