#!/usr/bin/env python3
"""aura-perf: a target without perf-worldline-measure still gets a tree.

The worker falls back to the auto-probe: top-level procedures are wrapped by
rewriting the live bindings, the kernel runs once, and the rows are read back
before the bindings are restored. The test drives one worker job directly, so
it exercises the same path a real trial takes without starting a round.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    aura = os.environ.get("AURA_BIN") or shutil.which("aura")
    if not aura:
        print("skip auto_probe_worker_test: no aura binary")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-auto-probe-"))
    try:
        seed = tmp / "seed.aura"
        seed.write_text(
            "(define (k-length xs) (length xs))\n"
            "(define (k-ref xs i) (list-ref xs i))\n"
            "(define (bench-kernel xs)\n"
            "  (let ((n (k-length xs)))\n"
            "    (let loop ((i 0) (acc 0))\n"
            "      (if (>= i n) acc (loop (+ i 1) (+ acc (k-ref xs i)))))))\n",
            encoding="utf-8",
        )
        screen = list(range(50))
        heldout = list(range(100))
        result = tmp / "result.json"
        job = {
            "id": "auto",
            "seed": str(seed),
            "target": "k-ref",
            "kernel": "bench-kernel",
            "null-genome": "(define (k-ref xs i) (list-ref xs i))\n",
            "role": "candidate",
            "genome": "(define (k-ref xs i) (list-ref xs i))\n",
            "heldout-n": 100,
            "heldout": {"input": heldout, "expected": sum(heldout)},
            "screen": {"input": screen, "expected": sum(screen)},
            "checks": [
                {"input": None, "expected": 0},
                {"input": [4], "expected": 4},
                {"input": [1, 2, 3], "expected": 6},
                {"input": [1, -2, 3], "expected": 2},
                {"input": [10, 0, 10], "expected": 20},
            ],
            "count-defines": 1,
            "count-names": [],
            "repeats": 3,
            "timeout-ms": 60000,
            "screen-n": 50,
            "screen-baseline-ms": -1,
            "screen-slack-ms": 5,
            "result": str(result),
            "job": str(tmp / "job.json"),
            "log": str(tmp / "trial.jsonl"),
        }
        (tmp / "job.json").write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ)
        env["AURA_SANDBOX"] = "off"
        env["AURA_PERF_JOB"] = str(tmp / "job.json")
        run = subprocess.run(
            [aura, "--preset", "dev", str(ROOT / "examples/sum-scan/worker.aura")],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        if run.returncode != 0:
            print(f"FAIL auto_probe_worker_test: worker rc={run.returncode}")
            print(run.stdout[-2000:])
            print(run.stderr[-2000:])
            return 1
        data = json.loads(result.read_text(encoding="utf-8"))
        nodes = {n["id"]: n for n in data.get("cct", {}).get("nodes", [])}
        base = {n["id"]: n for n in data.get("base-cct", {}).get("nodes", [])}
        failures = []
        if data.get("cct-source") != "auto-probe":
            failures.append(f"cct-source={data.get('cct-source')}")
        if data.get("status") != "ok" or data.get("checksum-ok") != 1:
            failures.append(f"status={data.get('status')} checksum={data.get('checksum-ok')}")
        if nodes.get("k-ref", {}).get("calls") != 50:
            failures.append(f"k-ref calls={nodes.get('k-ref', {}).get('calls')}")
        if base.get("k-ref", {}).get("calls") != 50:
            failures.append(f"base k-ref calls={base.get('k-ref', {}).get('calls')}")
        if nodes.get("k-length", {}).get("calls") != 1:
            failures.append(f"k-length calls={nodes.get('k-length', {}).get('calls')}")
        if failures:
            print("FAIL auto_probe_worker_test: " + "; ".join(failures))
            return 1
        print("ok auto_probe_worker_test: auto-probe rows in trial and base trees")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
