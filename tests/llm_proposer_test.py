#!/usr/bin/env python3
"""aura-perf#29: the model proposer in a real round, end to end.

A fake OpenAI-compatible server stands in for the provider. std/llm's
llm:chat reaches it over HTTP with the key the environment names, and
it answers with the candidates the test chooses. Three rounds, each in
a fresh directory:

  1. a faster, correct rewrite       the gate KEEPs the model's candidate
  2. a wrong rewrite the reply also
     marks "keep"                    ROLLBACK by checksum; the rule path
                                     still reaches its own KEEP
  3. no endpoint listening           llm-proposer names the transport's
                                     error; the round is the round without
                                     a provider

In every round the key is in no report line and in no file under out/.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "sk-test-SECRET-0123456789abcdef"
MODEL = "fake-model"

# The strategy genes the spec carries: one rule candidate a round.
# redundant-pass fails, and the round after it trials linear-scan.
# wrong-scale is in the catalog and out of the order.
ONE_AT_A_TIME = """; One rule candidate a round: redundant-pass fails, and the
          ; round after it trials linear-scan. wrong-scale is in the
          ; catalog and out of the order.
          "genes" (list (hash "id" "gene-one-at-a-time" "ratio" 2 "actionable-ms" 1
                                "per-round" 1
                                "order" (list "specialize-k-ref" "redundant-pass"
                                              "linear-scan")))"""


def free_port():
    """A TCP port nobody is listening on right now."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

REQUESTS = []
ANSWER = [None]


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        REQUESTS.append({"path": self.path,
                         "authorization": self.headers.get("Authorization"),
                         "body": json.loads(self.rfile.read(n) or b"{}")})
        content = ANSWER[0]
        if content is None:
            payload = {"error": {"message": "the test has no answer", "type": "server_error"}}
            code = 500
        else:
            payload = {"choices": [{"finish_reason": "stop", "index": 0,
                                    "message": {"role": "assistant", "content": content}}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            code = 200
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def candidates(*cands):
    return json.dumps({"candidates": list(cands)})


SPEC = """; The sum-scan target as an external spec, for the round tests
; (tests/llm_proposer_test.py, tests/checksum_round_test.py).
(require "lib/perf/loop" all:)
(require "lib/perf/util" all:)
(require "lib/perf/score" all:)

(define (call-kernel xs) (bench-kernel xs))

(define (aura-bin)
  (let ((b (getenv "AURA_BIN")))
    (if (and (string? b) (> (string-length b) 0)) b "aura")))

(define (region-cmd name)
  (string-append "env AURA_SANDBOX=off AURA_PERF_TIME=1 AURA_PERF_REGION=" name
                 " AURA_PERF_N=2000 AURA_PERF_REPS=3 "
                 (aura-bin) " examples/sum-scan/perf-region.aura"))

(define (regions)
  (let ((n 2000)
        (xs (perf:range 2000)))
    (list
      (hash "name" "bench-kernel" "calls" 1 "workload" #t
            "stack" (list "bench-kernel")
            "command" (region-cmd "bench-kernel")
            "thunk" (lambda () (bench-kernel xs)))
      (hash "name" "k-length" "calls" 1
            "stack" (list "bench-kernel" "k-length")
            "command" (region-cmd "k-length")
            "thunk" (lambda () (k-length xs)))
      (hash "name" "k-ref" "calls" n
            "stack" (list "bench-kernel" "k-ref")
            "command" (region-cmd "k-ref")
            "thunk" (lambda ()
                      (let loop ((i 0))
                        (if (>= i n) 0 (begin (k-ref xs i) (loop (+ i 1))))))))))

(define result
  (perf:autotune
    (hash "label" "llm-proposer-test"
          "seed-path" "examples/sum-scan/seed.aura"
          "worker" (getenv "AURA_PERF_WORKER")
          "target" "bench-kernel"
          "kernel" "bench-kernel"
          "out-dir" "out"
          "heldout-n" 3000
          "repeats" 3
          "profile-repeats" 2
          "min-speedup-pct" 20
          "screen-n" 600
          "screen-slack-ms" 5
          "intend" (hash "min-faster-pct" 10 "checksum" #t "budget" 4
                         "protected" (list "k-ref" "k-length"))
          %(genes)s
          "call" call-kernel
          "count-defines" #t
          "regions-fn" regions
          "catalog"
          (list (hash "id" "specialize-k-ref" "target" "k-ref"
                      "genome" %(specialize)s
                      "thought" "the hot leaf is list-ref; specializing it is the wrong site")
                (hash "id" "wrong-scale" "target" "bench-kernel"
                      "genome" %(wrong)s
                      "thought" "scale each element; checksum must reject it")
                (hash "id" "redundant-pass" "target" "bench-kernel"
                      "genome" %(redundant)s
                      "thought" "extra index walks; correct but slower")
                (hash "id" "linear-scan" "target" "bench-kernel"
                      "genome" %(linear)s
                      "thought" "one spine walk; expected to cut task-clock")))))
(display "done\\n")
(exit (if (and (hash? result) (= (hash-ref result "intend-met" 0) 1)) 0 1))
"""

# A correct rewrite the catalog does not have: (apply + xs) is the sum.
# On a fast machine it runs in under a millisecond and the held-out
# median reads 0 ms, which the gate takes as the largest speedup there
# is.
FAST = "(define (bench-kernel xs)\n  (apply + xs))"
# A rewrite with the right shape and the wrong result. The catalog's
# wrong-scale doubles each element; this one triples, so the proposer
# does not know it as a duplicate and the gate has to judge it.
WRONG = ("(define (bench-kernel xs)\n"
         "  (let ((n (k-length xs)))\n"
         "    (let loop ((i 0) (acc 0))\n"
         "      (if (>= i n)\n"
         "          acc\n"
         "          (loop (+ i 1) (+ acc (* (k-ref xs i) 3)))))))")


def write_project(tmp, genes=ONE_AT_A_TIME):
    """A fresh project: the example's target, the spec, and no memory."""
    scan = tmp / "examples" / "sum-scan"
    (tmp / "perf").mkdir(parents=True)
    scan.mkdir(parents=True)
    shutil.copy(ROOT / "examples/sum-scan/seed.aura", scan / "seed.aura")
    shutil.copy(ROOT / "examples/sum-scan/perf-region.aura", scan / "perf-region.aura")
    cands = ROOT / "examples/sum-scan/candidates"
    (tmp / "perf" / "spec.aura").write_text(SPEC % {
        "specialize": json.dumps("(define (k-ref xs i) (car xs))"),
        "wrong": json.dumps((cands / "wrong-scale.aura").read_text().rstrip("\n")),
        "redundant": json.dumps((cands / "redundant-pass.aura").read_text().rstrip("\n")),
        "linear": json.dumps((cands / "linear-scan.aura").read_text().rstrip("\n")),
        "genes": genes})


class Check:
    def __init__(self):
        self.fail = 0

    def that(self, name, ok, why=""):
        if ok:
            print(f"ok {name}")
        else:
            print(f"FAIL {name}" + (f": {why}" if why else ""))
            self.fail = 1
        return ok

    def line(self, name, report, prefix):
        hits = [ln for ln in report.splitlines() if ln.startswith(prefix)]
        return self.that(name, len(hits) == 1, f"want exactly one line starting {prefix!r}, got {hits}")


def run_round(tmp, base_url=None):
    """One autotune of the project. With a base URL the proposer is wired
    to it. Without one no LLM_* variable reaches the round, whatever the
    shell holds."""
    REQUESTS.clear()
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_")}
    if base_url is not None:
        env.update(LLM_API_KEY=KEY, LLM_BASE_URL=base_url, LLM_MODEL=MODEL)
    return subprocess.run([str(ROOT / "bin" / "aura-perf"), "autotune", "perf/spec.aura"],
                          cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=600)


def key_leaks(tmp, run):
    """Every file under out/, the round's stdout and its stderr."""
    found = []
    for p in sorted((tmp / "out").rglob("*")):
        if p.is_file() and KEY.encode() in p.read_bytes():
            found.append(str(p.relative_to(tmp)))
    for name, text in (("stdout", run.stdout), ("stderr", run.stderr)):
        if KEY in text:
            found.append(name)
    return found


def main():
    check = Check()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    dead = f"http://127.0.0.1:{free_port()}/v1"  # a port nothing listens on

    # ── 1. a faster, correct rewrite ──────────────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-llm-keep-"))
    write_project(tmp)
    ANSWER[0] = candidates({"id": "Sum via apply", "target": "bench-kernel",
                            "thought": "the library's own fold over the list\nin one call",
                            "genome": "```\n" + FAST + "\n```"})
    run = run_round(tmp, base)
    report = (tmp / "out" / "report.txt").read_text() if (tmp / "out" / "report.txt").is_file() else ""
    lines = report.splitlines()
    kept = [ln for ln in lines if ln.startswith("kernel KEEP id=llm-")]

    check.that("keep: one call reached the provider", len(REQUESTS) == 1, str(len(REQUESTS)))
    if REQUESTS:
        req = REQUESTS[0]
        body = req["body"]
        msgs = body.get("messages", [])
        user = next((m.get("content") for m in msgs if m.get("role") == "user"), "")
        system = next((m.get("content") for m in msgs if m.get("role") == "system"), "")
        check.that("keep: the key went as a bearer token",
                   req["authorization"] == f"Bearer {KEY}", repr(req["authorization"]))
        check.that("keep: to <base>/chat/completions", req["path"] == "/v1/chat/completions", req["path"])
        check.that("keep: the model is the environment's", body.get("model") == MODEL, str(body.get("model")))
        check.that("keep: reasoning_effort is low", body.get("reasoning_effort") == "low")
        check.that("keep: max_tokens leaves room for the thinking",
                   isinstance(body.get("max_tokens"), int) and body["max_tokens"] >= 4096,
                   str(body.get("max_tokens")))
        check.that("keep: two messages, system then user",
                   [m.get("role") for m in msgs] == ["system", "user"], str([m.get("role") for m in msgs]))
        check.that("keep: the evidence is text", isinstance(user, str) and isinstance(system, str))
        check.that("keep: the evidence is the profile",
                   "hotspot k-ref" in user and "hotspot bench-kernel" in user and "stack=bench-kernel>k-ref" in user,
                   user[:300])
        check.that("keep: the evidence shows the target's source and the gate",
                   "(define (bench-kernel xs)" in user and "gate: a candidate is kept only when" in user)
        check.that("keep: no image, no data URL",
                   "image_url" not in user and "data:" not in user)
        check.that("keep: the model is told it does not decide", "You do not" in system)
    check.line("keep: llm-proposer ok", report, "llm-proposer ok model=fake-model")
    cand = [ln for ln in lines if ln.startswith("llm-candidate llm-")]
    check.that("keep: the candidate is named", len(cand) == 1, str(cand))
    cid = cand[0].split()[1] if cand else "llm-?"
    check.that("keep: the genome's fences were not part of it",
               "target=bench-kernel" in cand[0] and "in one call" in cand[0]
               and "\n" not in cand[0], cand[0] if cand else "")
    check.that("keep: the candidate joined the rule path's round",
               f"round 1 candidates redundant-pass,{cid}" in lines,
               str([ln for ln in lines if ln.startswith("round 1 candidates")]))
    check.line("keep: the gate passed it", report, f"candidate {cid} PASS reason=gate-pass")
    check.that("keep: the gate KEPT it, being the only candidate that passed",
               len(kept) == 1 and kept[0].startswith(f"kernel KEEP id={cid} "), str(kept))
    check.line("keep: the model's trial is the model's budget", report, "llm-budget-used 1")
    check.line("keep: the intend's budget is the rule path's", report, "budget-used 1")
    check.that("keep: intend met, exit 0",
               run.returncode == 0 and lines and lines[0].startswith("verdict intend-met=1"),
               f"rc={run.returncode} {lines[:1]}")
    evidence = json.loads((tmp / "out" / "evidence.json").read_text())
    llm = [c for c in evidence["candidates"] if c.get("proposer") == "llm"]
    check.that("keep: the evidence keeps the provenance",
               len(llm) == 1 and llm[0]["id"] == cid and llm[0].get("thought") == "the library's own fold over the list in one call",
               str(llm))
    check.that("keep: the evidence carries no key", not key_leaks(tmp, run), str(key_leaks(tmp, run)))
    shutil.rmtree(tmp, ignore_errors=True)

    # ── 2. a wrong rewrite the reply marks "keep" ─────────────────
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-llm-wrong-"))
    write_project(tmp)
    ANSWER[0] = candidates({"id": "double", "target": "bench-kernel",
                            "thought": "twice each element", "genome": WRONG,
                            "keep": True, "decision": "KEEP", "status": "gate-pass",
                            "heldout-ms": 1, "checksum-ok": 1})
    run = run_round(tmp, base)
    report = (tmp / "out" / "report.txt").read_text()
    lines = report.splitlines()
    rolled = [ln for ln in lines if ln.startswith("candidate llm-")
              and re.search(r" ROLLBACK reason=(infeasible: )?checksum", ln)]
    check.that("wrong: the gate rolled it back on the checksum", len(rolled) == 1, str(rolled))
    check.that("wrong: the reply's keep changed nothing",
               not any(ln.startswith("kernel KEEP id=llm-") for ln in lines))
    check.that("wrong: the rule path went on to its own KEEP",
               any(ln.startswith("kernel KEEP id=linear-scan") for ln in lines)
               and any(ln.startswith("round 2 candidates linear-scan") for ln in lines),
               str([ln for ln in lines if ln.startswith(("round", "kernel"))]))
    check.that("wrong: intend met, exit 0",
               run.returncode == 0 and lines[0].startswith("verdict intend-met=1"), f"rc={run.returncode}")
    check.that("wrong: the evidence carries no key", not key_leaks(tmp, run), str(key_leaks(tmp, run)))
    shutil.rmtree(tmp, ignore_errors=True)

    # ── 3. no endpoint listening ──────────────────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-llm-down-"))
    write_project(tmp)
    ANSWER[0] = candidates({"id": "sum", "target": "bench-kernel", "genome": FAST})
    run = run_round(tmp, dead)
    report = (tmp / "out" / "report.txt").read_text()
    lines = report.splitlines()
    proposer = [ln for ln in lines if ln.startswith("llm-proposer ")]
    check.that("down: the transport's error is the proposer's line",
               len(proposer) == 1 and proposer[0].startswith("llm-proposer http-post:"), str(proposer))
    check.that("down: the provider was not asked twice", len(REQUESTS) == 0, str(len(REQUESTS)))
    check.that("down: the round is the round without a provider",
               "round 1 candidates redundant-pass" in lines
               and any(ln.startswith("kernel KEEP id=linear-scan") for ln in lines)
               and "llm-budget-used 0" in lines,
               str([ln for ln in lines if ln.startswith(("round", "kernel", "llm"))]))
    check.that("down: intend met, exit 0",
               run.returncode == 0 and lines[0].startswith("verdict intend-met=1"), f"rc={run.returncode}")
    check.that("down: the evidence carries no key", not key_leaks(tmp, run), str(key_leaks(tmp, run)))
    shutil.rmtree(tmp, ignore_errors=True)

    server.shutdown()
    sys.exit(check.fail)


if __name__ == "__main__":
    main()
