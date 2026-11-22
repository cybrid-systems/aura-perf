#!/usr/bin/env python3
"""aura-perf#27: attach-only mode against an external host bus.

A separate aura process hosts the workspace (bus:host + a choose-fn
define + node projection + a baseline metric). perf attaches attach-only
(AURA_PERF_BUS_HOST=0) with caps read|publish|trial (7) — no keep bit —
consumes the host signals, proposes a source-carrier patch with the
five-tuple evidence, and the test verifies the worldline stays pending
(state 0, not kept). Needs a bus-capable Aura (std/bus + the v0.3.1
closed-loop verbs) via AURA_BIN; skipped otherwise.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AURA = os.environ.get("AURA_BIN", "aura")
WS = 994

HOST = """(require "std/bus" all:)
(set-code "(define (choose-fn x) (+ x 1)) (define (admit-fn x) 1)")
(eval-current)
(define h (bus:host {ws}))
(define ms (bus:attach "" {ws} 3 127 255))
(define msid (car (cdr ms)))
(bus:project-nodes msid)
(bus:publish msid 9 40)
; The host's define names and node ids (aura#5397): the ids live in the
; host's workspace AST, so only the host can answer.
(display "DEFS=") (display (list-ref (bus:defines msid) 3)) (display "|")
(newline)
(display "HOST-READY") (newline)
(let loop ()
  (let ((l (read-line)))
    (cond
      ((eof-object? l) #f)
      ((string=? l "choose")
       (display "choose=") (display (choose-fn 5)) (display "|") (newline)
       (loop))
      (else (loop)))))
(bus:detach msid)
(bus:unhost {ws})
(display "HOST-DONE") (newline)
"""

# perf in attach-only mode: caps 7, signals, one evidence-bound proposal,
# then a clean detach (the worldline stays pending for the judge).
PERF = """(require "std/bus" all:)
(require "std/string" all:)
(require "std/bitwise" all:)
(require "lib/perf/bus" all:)
(define buf (hash "lines" '() "brief" '()))
(define spec (hash "bus" (hash "workspace" {ws})))
(define bus (perf:bus-start spec buf))
(display (if bus "perf-attach-ok" "perf-attach-FAIL")) (newline)
(display (string-append "caps=" (number->string (hash-ref bus "caps" -1)))) (newline)
(display (string-append "keep-bit="
                        (if (= 0 (bitwise-and (hash-ref bus "caps" 0) 8)) "0" "1")))
(newline)
(define rows (perf:bus-subscribe-signals bus buf))
(display (string-append "signals="
                        (if (and (pair? rows) (pair? (car rows))
                                 (= 9 (car (car rows))) (= 40 (car (cdr (car rows)))))
                            "ok" "FAIL")))
(newline)
; The host projected its nodes; find the choose-fn define node (kind 8).
(define sid (hash-ref bus "session"))
(define nq (bus:query sid 5 0 0))
(define node (let loop ((rows (if (bus:ok? nq) (list-ref nq 4) '())))
               (cond ((null? rows) -1)
                     ((= 8 (car (car rows))) (car (cdr (car rows))))
                     (else (loop (cdr rows))))))
(display (string-append "node=" (number->string node))) (newline)
(define wl (perf:bus-propose bus node "(lambda (x) (+ x 10))" 7 42 31))
(display (string-append "wl=" (number->string wl))) (newline)
; The worldline record the coordinator projected: state 0 = pending.
(define wq (bus:query sid 4 0 0))
(define state (let loop ((rows (if (bus:ok? wq) (list-ref wq 4) '())) (st -1))
                (cond ((null? rows) st)
                      ((= wl (car (car rows))) (loop (cdr rows) (list-ref (car rows) 2)))
                      (else (loop (cdr rows) st)))))
(display (string-append "state=" (number->string state))) (newline)
; The coordinator's digest of the trial's committed patch bytes is
; nonzero: the source-carrier patch really committed and the five-tuple
; bind succeeded (perf:bus-propose returns the wl only after a successful
; bus:bind-evidence). The evidence tail is projected into the worldline
; record at verdict time; a pending trial keeps its five-tuple in the
; coordinator's ledger, where the judge's KEEP re-checks it.
(define dg (bus:candidate-digest sid wl))
(display (string-append "digest="
                        (if (and (bus:ok? dg) (> (car (cdr dg)) 0)) "ok" "FAIL")))
(newline)
; The multi-function proposal (aura#5397): one worldline carries a patch
; per function, so the host's KEEP applies the set atomically.
(define dn (perf:bus-define-nodes bus))
(display (string-append "defs="
                        (if dn "ok" "FAIL"))) (newline)
(define mwl (perf:bus-propose-multi bus
                               (list (list "choose-fn" "(lambda (x) (+ x 10))")
                                     (list "admit-fn" "(lambda (x) 7)"))
                               7 42 31))
(display (string-append "mwl=" (number->string mwl))) (newline)
(perf:bus-finish bus buf 100 50)
(display "perf-done") (newline)
; The run buffer carries the attach/proposal report lines.
(let loop ((xs (reverse (hash-ref buf "lines" '()))))
  (if (null? xs) #f
      (begin (display (car xs)) (newline) (loop (cdr xs)))))
"""

# A witness peer (the judge's seat) reads the worldline AFTER perf
# detached: still pending — perf never kept it.
WITNESS = """(require "std/bus" all:)
(define s (bus:attach "" {ws} 2 3 255))
(define sid (car (cdr s)))
(define wq (bus:query sid 4 0 0))
(define pending
  (let loop ((rows (if (bus:ok? wq) (list-ref wq 4) '())) (found #f))
    (cond ((null? rows) found)
          ((and (= 1 (car (car rows))) (= 0 (list-ref (car rows) 2)))
           (loop (cdr rows) #t))
          (else (loop (cdr rows) found)))))
(display (if pending "WITNESS-PENDING-OK" "WITNESS-PENDING-FAIL")) (newline)
(bus:detach sid)
"""


def skip(msg):
    print(f"skip bus_attach_test: {msg}")
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

    rt = tempfile.mkdtemp(prefix="aura-perf-attach-")
    sock = Path(rt) / "aura" / "bus" / f"{WS}.sock"
    env = dict(os.environ, XDG_RUNTIME_DIR=rt, AURA_SANDBOX="off",
               AURA_BIN=str(aura), AURA_PATH=str(ROOT),
               AURA_PERF_BUS_HOST="0")
    hostf = Path(rt) / "host.aura"
    hostf.write_text(HOST.format(ws=WS))
    perf = Path(rt) / "perf.aura"
    perf.write_text(PERF.format(ws=WS))
    witness = Path(rt) / "witness.aura"
    witness.write_text(WITNESS.format(ws=WS))

    fail = 0
    hostp = subprocess.Popen([str(aura), "--quiet", str(hostf)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=env)
    try:
        ready = False
        for _ in range(300):
            if sock.exists():
                ready = True
                break
            if hostp.poll() is not None:
                break
            time.sleep(0.1)
        # The host prints its define names before the ready marker, so
        # read until the marker rather than one line.
        line = ""
        if ready:
            for _ in range(20):
                line = hostp.stdout.readline()
                if not line or "HOST-READY" in line:
                    break
        if not ready or "HOST-READY" not in line:
            print("FAIL attach: external host never became ready")
            print(line, hostp.stdout.read() if hostp.poll() is not None else "")
            sys.exit(1)

        r = subprocess.run([str(aura), "--quiet", str(perf)],
                           capture_output=True, text=True, env=env, timeout=60,
                           cwd=ROOT)
        out = r.stdout
        checks = [
            ("perf-attach-ok", "perf attached to the external host"),
            ("caps=7", "granted caps are read|publish|trial (7)"),
            ("keep-bit=0", "perf holds no keep bit"),
            ("signals=ok", "perf consumed the host's baseline metric"),
            ("digest=ok", "candidate digest committed (patch bytes in the image)"),
            ("defs=ok", "perf asked the host for its define names"),
            ("state=0", "worldline is pending, not kept"),
            ("perf-done", "perf detached cleanly"),
        ]
        wl_ok = False
        for ln in out.splitlines():
            if ln.startswith("wl="):
                try:
                    wl_ok = int(ln[3:]) > 0
                except ValueError:
                    pass
        if not wl_ok:
            print("FAIL attach: no proposal worldline")
            print(out, r.stderr[:400])
            fail = 1
        mwl_ok = False
        for ln in out.splitlines():
            if ln.startswith("mwl="):
                try:
                    mwl_ok = int(ln[4:]) > 0
                except ValueError:
                    pass
        if not mwl_ok:
            print("FAIL attach: no multi-function proposal worldline")
            print(out, r.stderr[:400])
            fail = 1
        for marker, what in checks:
            if marker in out:
                print(f"ok attach: {what}")
            else:
                print(f"FAIL attach: {what}")
                print(out, r.stderr[:400])
                fail = 1
        if "mode=attach-only" in out and "bus-proposed wl=" in out:
            print("ok attach: report lines name mode=attach-only and the pending proposal")
        else:
            print("FAIL attach: report lines missing mode=attach-only / bus-proposed")
            fail = 1

        w = subprocess.run([str(aura), "--quiet", str(witness)],
                           capture_output=True, text=True, env=env, timeout=30)
        if "WITNESS-PENDING-OK" in w.stdout:
            print("ok attach: judge seat sees the proposal still pending after perf detached")
        else:
            print("FAIL attach: witness could not confirm the pending worldline")
            print(w.stdout, w.stderr[:300])
            fail = 1

        # The host's workspace is untouched: perf proposed, never applied.
        hostp.stdin.write("choose\n")
        hostp.stdin.flush()
        cl = hostp.stdout.readline()
        if "choose=6" in cl:
            print("ok attach: host choose-fn unchanged (proposal not applied by perf)")
        else:
            print(f"FAIL attach: host workspace changed: {cl.strip()}")
            fail = 1
    finally:
        try:
            hostp.stdin.close()
            hostp.wait(timeout=10)
        except Exception:
            hostp.kill()
            hostp.wait()
        import shutil
        shutil.rmtree(rt, ignore_errors=True)
    sys.exit(fail)


if __name__ == "__main__":
    main()
