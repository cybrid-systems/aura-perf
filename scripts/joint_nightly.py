#!/usr/bin/env python3
"""The three-repo joint nightly (aura#5397).

aura-redis hosts the workspace and owns the real RESP data plane,
aura-perf proposes, aura-harness judges. The lane pins three repo
commits, runs a phase-switching load (read/write ratio, TTL peak, poison
storm) against the real server, and checks the four v0.3.1 acceptance
criteria plus the held-out net benefit on real load:

  1. self-adaptation: the policy changes under a load switch with no
     human edit and no restart;
  2. hidden-load net benefit: the kept policy beats the pre-switch
     baseline on a held-out load the proposer never saw;
  3. no false commit: a crash, a stale baseline, an unmatched candidate
     hash or an impure body is refused and the live tree stays whole;
  4. replayable: the audit reconstructs the lineage and every KEEP
     reproduces offline from its reproduction package.

The report lands in the report directory; a regression fails the lane.

usage: joint_nightly.py --report DIR [--phase-seconds N] [--phases a,b,c]

Environment:
  AURA_BIN            the bus-capable aura binary (the host's runtime)
  AURA_REDIS_DIR      the aura-redis checkout
  AURA_HARNESS_DIR    the aura-harness checkout
  AURA_PERF_DIR       this checkout
  JOINT_WS            the bus workspace id (default 8801)
  JOINT_PORT          the RESP port (default 16399)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The four v0.3.1 acceptance criteria (#5376) this lane measures.
CRITERIA = ("self-adaptation", "hidden-net-benefit", "no-false-commit", "replayable")


def _aura() -> str:
    binary = os.environ.get("AURA_BIN", "aura")
    if not Path(binary).is_file():
        raise SystemExit(f"error: AURA_BIN={binary} is not a file")
    return binary


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("AURA_SANDBOX", "off")
    env.setdefault("AURA_PIPELINE_STRICT", "0")
    if extra:
        env.update(extra)
    return env


def _lib_for(binary: str) -> str:
    lib = Path(binary).resolve().parent.parent / "lib"
    return str(lib) if lib.is_dir() else ""


def _command(*args: str) -> bytes:
    """One RESP command array (the data plane speaks standard RESP)."""
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        raw = arg.encode()
        out.append(f"${len(raw)}\r\n".encode() + raw + b"\r\n")
    return b"".join(out)


def _ping(port: int) -> bool:
    """The data plane answers a PING with +PONG."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
            sock.sendall(_command("PING"))
            return b"PONG" in sock.recv(64)
    except OSError:
        return False


def _drain(proc: subprocess.Popen, sink: list[str]) -> None:
    """Read a child's output into a list, so the lane can look for the
    lines it needs while the child keeps running."""
    try:
        for line in proc.stdout:
            sink.append(line)
    except Exception:
        pass


def _run(cmd: list[str], env: dict[str, str], timeout: int = 300,
         cwd: str | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return done.returncode, done.stdout + done.stderr


class Report:
    """The lane's report: the criteria, their evidence and the verdict."""

    def __init__(self) -> None:
        self.criteria: dict[str, dict] = {}
        self.notes: list[str] = []

    def set(self, name: str, ok: bool, detail: str, evidence: str = "") -> None:
        self.criteria[name] = {"ok": bool(ok), "detail": detail, "evidence": evidence}

    @property
    def ok(self) -> bool:
        return all(entry["ok"] for entry in self.criteria.values())

    def write(self, path: Path) -> None:
        payload = {
            "criteria": self.criteria,
            "notes": self.notes,
            "ok": self.ok,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        lines = [f"joint_nightly: {'OK' if self.ok else 'FAIL'}"]
        for name in sorted(self.criteria):
            entry = self.criteria[name]
            lines.append(f"  [{'ok' if entry['ok'] else 'FAIL'}] {name}: {entry['detail']}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        (path.parent / "report.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))


def _free_port() -> int:
    """A port nobody is listening on: the lane must talk to the server
    it started, not to a leftover from an earlier run."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _redis_server(redis_dir: Path, port: int) -> subprocess.Popen | None:
    """Start the real RESP data plane (the C server when it is built)."""
    candidates = [
        redis_dir / "native" / "build" / "aura_redis_server",
        redis_dir / "native" / "build" / "Release" / "aura_redis_server",
    ]
    binary = next((c for c in candidates if c.is_file()), None)
    if binary is None:
        return None
    proc = subprocess.Popen(
        # The memory limit is the probe's yardstick: the churn has to
        # exceed it (so the eviction path runs) and the hidden set has
        # to fit in it (so it is a share of the keyspace).
        [str(binary), "--port", str(port), "--maxmemory", "200000",
         # The server starts on the age-based kernel: without a memory
         # limit and an eviction policy there is nothing to measure.
         "--evict", "lru"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if _ping(port):
            return proc
        time.sleep(0.1)
    proc.kill()
    return None


def _live_policy(port: int) -> str:
    """The eviction kernel the server runs now."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
            sock.sendall(_command("EVICT"))
            return sock.recv(64).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _info(port: int, section: str = "stats") -> dict:
    """One INFO section as a dict."""
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
        sock.sendall(_command("INFO", section))
        raw = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw += chunk
            if not raw.startswith(b"$"):
                break
            head, _, rest = raw.partition(b"\r\n")
            try:
                length = int(head[1:])
            except ValueError:
                break
            if len(rest) >= length + 2:
                raw = rest[:length]
                break
    out: dict = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            out[key] = value
    return out


def _held_out_probe(port: int, prefix: str, keys: int = 200) -> dict:
    """The hidden held-out set: the lane owns these keys, the proposer
    never sees them. Writes them, drops the cache view and reads them
    back under the live policy, so the hit rate reflects the policy the
    host is running."""
    import socket
    conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    conn.settimeout(2.0)
    names = [f"{prefix}{i}" for i in range(keys)]
    for name in names:
        conn.sendall(_command("SET", name, "v" * 32))
    conn.recv(4096)
    before = _info(port)
    hits0 = int(before.get("hits", 0))
    misses0 = int(before.get("misses", 0))
    for name in names:
        conn.sendall(_command("GET", name))
    conn.recv(65536)
    after = _info(port)
    conn.close()
    hits = int(after.get("hits", 0)) - hits0
    misses = int(after.get("misses", 0)) - misses0
    total = hits + misses
    return {"hits": hits, "misses": misses,
            "hit_pct": (100 * hits // total) if total else 0}


def _held_out_ab(port: int, prefix: str, candidate_policy: str,
                 baseline_policy: str, rounds: int = 4, hot: int = 64,
                 churn: int = 4000) -> dict:
    """The held-out A/B on the real server.

    The lane owns the hidden key set: the proposer never sees these
    keys, so the net benefit it measures is out-of-sample. Each round
    writes the hidden hot set, drives a churn storm that evicts, then
    reads the hot set back and counts the hits. The candidate policy
    and the baseline policy are measured on the same traffic, so the
    difference is the candidate's net benefit.

    -> {"windows": [ppm per round], "observed_ppm": int}
    """
    import socket
    conn = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    conn.settimeout(5.0)
    conn.sendall(_command("EVICT", baseline_policy))

    def drain() -> None:
        conn.setblocking(False)
        try:
            while conn.recv(262144):
                pass
        except BlockingIOError:
            pass
        finally:
            conn.setblocking(True)

    def get(key: str) -> int:
        conn.sendall(_command("GET", key))
        reply = conn.recv(65536)
        return 0 if reply.startswith(b"$-1") else 1

    def run(policy: str) -> list[int]:
        conn.sendall(_command("EVICT", policy))
        drain()
        per_round: list[int] = []
        for rnd in range(rounds):
            for i in range(hot):
                conn.sendall(_command("SET", f"{prefix}{i}", "h" * 64))
            drain()
            hits = 0
            for i in range(hot):
                hits += get(f"{prefix}{i}")
            drain()
            for i in range(churn):
                conn.sendall(_command("SET", f"{prefix}churn{rnd}_{i}", "c" * 64))
            drain()
            per_round.append(100 * hits // max(1, hot))
        return per_round

    baseline = run(baseline_policy)
    candidate = run(candidate_policy)
    conn.close()
    # The per-fold delta in parts per million: positive means the
    # candidate kept more of the hidden set.
    windows = [(c - b) * 10000 for b, c in zip(baseline, candidate)]
    observed = sum(windows) // max(1, len(windows))
    return {"baseline_pct": baseline, "candidate_pct": candidate,
            "windows": windows, "observed_ppm": observed}


class BackgroundLoad:
    """A live workload while the judge measures.

    The judge reads the host's published metrics to learn which kernel
    the candidate would pick: those metrics are per-tick deltas, so the
    workload has to be running while the judge looks. The load is the
    lane's own — the hidden key set is the judge's.

    Use it as a context manager.
    """

    def __init__(self, port: int):
        self.port = port
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def _run(self) -> None:
        import socket
        conn = socket.create_connection(("127.0.0.1", self.port), timeout=5.0)
        conn.settimeout(5.0)
        i = 0
        while not self.stop.is_set():
            i += 1
            # A miss-heavy workload: the host's metrics then say the
            # workload misses, which is the regime the candidate and the
            # control differ in.
            if i % 4 == 0:
                conn.sendall(_command("SET", f"j{i % 500}", "v" * 48))
            else:
                conn.sendall(_command("GET", f"miss-{i}"))
            try:
                conn.recv(4096)
            except OSError:
                break
        conn.close()

    def __enter__(self) -> "BackgroundLoad":
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=5)


def _load_phase(port: int, seconds: float, phase: str) -> dict:
    """One load phase against the real server: a read/write ratio, a TTL
    peak or a poison-key storm, depending on the phase."""
    import socket
    stats = {"phase": phase, "ops": 0, "errors": 0}
    deadline = time.monotonic() + seconds
    conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    conn.settimeout(2.0)
    key = 0
    # A bounded key space: the load is a workload, not a key-space
    # filler. The judge's held-out probe has to face the server's own
    # eviction pressure, so the load's keys stay a working set.
    while time.monotonic() < deadline:
        key += 1
        slot = key % 100
        if phase == "write_heavy":
            cmd = _command("SET", f"j{slot}", "v" * 64)
        elif phase == "ttl_peak":
            cmd = _command("SET", f"t{slot}", "v" * 64, "PX", "200")
        elif phase == "poison_storm":
            cmd = _command("SET", f"u{slot}", "v" * 256)
        else:  # read_heavy: cold reads, the regime that punishes the
            # age-based kernel (the hidden set is read, the churn is not)
            cmd = _command("GET", f"cold{slot}")
        try:
            conn.sendall(cmd)
            conn.recv(256)
            stats["ops"] += 1
        except OSError:
            stats["errors"] += 1
            break
    conn.close()
    return stats


def _fetch_repro(aura: str, env: dict[str, str], ws: int, worldline: int) -> dict:
    """Ask the coordinator for the reproduction package of a worldline.

    The query runs in its own process: it is a one-shot artifact fetch,
    and the answer must not depend on the state of a long-lived peer.
    """
    script = ROOT / "scripts" / "joint_repro.aura"
    if not script.is_file():
        return {"ok": False, "reason": f"the repro client is missing: {script}"}
    run_env = dict(env)
    run_env["JOINT_REPRO_WS"] = str(ws)
    run_env["JOINT_REPRO_WL"] = str(worldline)
    rc, out = _run([aura, str(script)], run_env, timeout=60)
    for line in out.splitlines():
        if not line.startswith("repro="):
            continue
        payload = line[len("repro="):].rstrip("|")
        if payload.startswith("{"):
            return {"ok": True, "json": payload}
        return {"ok": False, "reason": payload or "the repro query failed", "rc": rc}
    return {"ok": False, "reason": f"the repro client did not answer (rc={rc})", "out": out[-6000:]}


def _harness_judge(harness_dir: Path, ws: int, worldline: int, grant_token: str,
                   aura: str, env: dict[str, str], port: int,
                   baseline_policy: str, host: str = "127.0.0.1",
                   control_worldline: int = 0,
                   control_token: str = "") -> tuple[dict, str]:
    """Drive the real aura-harness judge: it activates the host's scoped
    keep grant, binds the held-out evidence, and KEEPs (or rolls back)
    the worldline under that grant.

    The harness is the judge: its regression replay decides pass/fail, and
    it holds the hidden set the proposer never saw.
    """
    sys.path.insert(0, str(harness_dir))
    try:
        from aura_harness.control import AuraHarness
    except Exception as exc:  # the harness is optional in the checkout
        return {"ok": False, "reason": f"harness-import-failed: {exc}"}, ""

    judge_env = dict(env)
    judge_env["AURA_HARNESS_BUS_WORKSPACE"] = str(ws)
    judge_env["AURA_BIN"] = aura
    judge_env.setdefault("AURA_LIB", _lib_for(aura))
    os.environ.update({k: v for k, v in judge_env.items() if isinstance(v, str)})

    out: dict = {}
    harness = None

    def step(msg: str) -> None:
        print(f"[judge] {msg}", flush=True)

    try:
        step("start the harness")
        harness = AuraHarness("ws")
        step("harness up")
        # The harness attaches to the workspace bus when it starts (the
        # bus face is opt-in through AURA_HARNESS_BUS_WORKSPACE); the
        # judge uses that session — a second attach would be a second
        # session for the same peer.
        probe = harness.bus_worldlines()
        out["attached"] = bool(probe.get("ok"))
        out["attach_lines"] = [str(probe)]
        if not out["attached"]:
            return {"ok": False, "reason": f"the harness did not attach: {probe}"}, json.dumps(out)
        # The scoped grant: the host's token, delivered out of band.
        granted = harness.bus_grant(int(grant_token), worldline)
        out["grant"] = granted
        if not granted.get("ok"):
            return {"ok": False, "reason": f"grant-refused: {granted}"}, json.dumps(out)
        # The round's negative control: the judge measures the control
        # the same way and binds its evidence first. The coordinator
        # refuses the round unless the statistics reject the control.
        if control_worldline and control_token:
            step("activate the control's grant")
            ctrl_grant = harness.bus_grant(int(control_token), control_worldline)
            out["control_grant"] = ctrl_grant
        # The held-out measurement: the judge owns a hidden key set on
        # the real data plane and measures the candidate's eviction
        # kernel against the baseline's. The proposer never sees that
        # key set, so the measurement is out-of-sample. The round's
        # control is measured in the same pass, so both kernels are read
        # under the same regime.
        step("measure")
        heldout = harness.bus_heldout(worldline, host, port,
                                      control_wl=control_worldline)
        step(f"measured {heldout}")
        out["heldout"] = heldout
        window = int(heldout.get("window", 0))
        ctrl_window = int(heldout.get("control_window", 0))
        windows = heldout.get("windows") or [window]
        ctrl_windows = heldout.get("control_windows") or [ctrl_window]
        if control_worldline and control_token:
            # The control's evidence binds under the control's own grant:
            # a scoped grant reaches nothing else.
            out["control_gate"] = harness.bus_gate(
                control_worldline, 700, 7, 42, 31, len(ctrl_windows), 0, 1, 1, ctrl_windows)
        # The candidate's grant again: only the grant scoped to a
        # worldline may bind that worldline's evidence or keep it.
        harness.bus_grant(int(grant_token), worldline)
        if not heldout.get("ok"):
            out["gate"] = {"ok": False, "detail": heldout.get("detail")}
            out["judge"] = {"ok": False, "verdict": "none",
                            "reason": "held-out-measurement-failed"}
            return out, json.dumps(out)
        # The held-out evidence: the judge hands the raw windows it
        # measured to the coordinator, which recomputes the verdict.
        # It binds BEFORE the KEEP: the coordinator refuses a KEEP whose
        # statistical evidence is missing.
        gate = harness.bus_gate(worldline, 700, 7, 42, 31, len(windows), 0, 0, 1, windows)
        out["gate"] = gate
        # The judge decides: its own regression replay on the hidden set.
        # An empty verdict runs the replay; "fail" forces the outcome.
        step("judge")
        judged = harness.bus_judge(worldline, "")
        step(f"the verdict {judged}")
        out["judge"] = judged
        # The negative control is never applied: the judge tries to keep
        # it and the coordinator refuses. That refusal is the no-false-
        # The reproduction package, then the control's refusal attempt:
        # the package is the verdict the offline re-run checks.
        out["repro"] = _fetch_repro(aura, env, ws, worldline)
        # commit evidence: a known-harmful candidate cannot land.
        if control_worldline and control_token:
            harness.bus_grant(int(control_token), control_worldline)
            refused = harness.bus_judge(control_worldline, "pass")
            out["control_judge"] = refused
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        if harness is not None:
            try:
                harness.close()
            except Exception:
                pass
    return out, json.dumps(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="the report directory")
    parser.add_argument("--phase-seconds", type=float, default=3.0)
    # The last phase decides the policy the host is left running: the
    # TTL-pressure regime ends it on the age-based kernel, which is the
    # one the hidden set punishes.
    parser.add_argument("--phases", default="write_heavy,read_heavy,poison_storm,ttl_peak")
    args = parser.parse_args()

    report = Report()
    report_dir = Path(args.report)
    report_dir.mkdir(parents=True, exist_ok=True)

    aura = _aura()
    perf_dir = Path(os.environ.get("AURA_PERF_DIR", ROOT))
    redis_dir = Path(os.environ.get("AURA_REDIS_DIR", ""))
    harness_dir = Path(os.environ.get("AURA_HARNESS_DIR", ""))
    ws = int(os.environ.get("JOINT_WS", "8801"))
    port = int(os.environ.get("JOINT_PORT", "0")) or _free_port()
    # The baseline eviction kernel: the candidate is measured against
    # it on the hidden key set.
    baseline_policy = os.environ.get("JOINT_BASELINE_POLICY", "lru")
    host = os.environ.get("JOINT_HOST", "127.0.0.1")

    for name, path in (("aura-redis", redis_dir), ("aura-harness", harness_dir)):
        if not path.is_dir():
            report.set("self-adaptation", False, f"the {name} checkout is missing ({path})")
            report.write(report_dir / "report.json")
            return 1

    server = _redis_server(redis_dir, port)
    if server is None:
        report.set("self-adaptation", False,
                   "the real RESP data plane is not built "
                   "(native/build/aura_redis_server)")
        report.write(report_dir / "report.json")
        return 1
    try:
        if not _ping(port):
            report.set("self-adaptation", False, "the RESP server did not answer PING")
            report.write(report_dir / "report.json")
            return 1

        # The server's own memory state: the probe's discrimination
        # depends on the eviction path running at all.
        mem = _info(port)
        report.notes.append(
            f"server: maxmemory={mem.get('maxmemory')} used={mem.get('used_memory')} "
            f"evicted={mem.get('evicted')} keys={mem.get('keys')}")

        # ── the phases: the load switches under the closed loop ──
        phases = [p.strip() for p in args.phases.split(",") if p.strip()]
        phase_stats = []
        for phase in phases:
            phase_stats.append(_load_phase(port, args.phase_seconds, phase))
        (report_dir / "phases.json").write_text(
            json.dumps(phase_stats, indent=2, sort_keys=True) + "\n")
        ops = sum(p["ops"] for p in phase_stats)
        report.notes.append(f"load phases: {len(phase_stats)} ({ops} ops)")

        with tempfile.TemporaryDirectory(prefix="joint-") as tmp:
            xdg = tmp
            env = _env({
                "XDG_RUNTIME_DIR": xdg,
                "AURA_REDIS_BUS_WORKSPACE": str(ws),
                "AURA_REDIS_PORT": str(port),
                "AURA_REDIS_HOST": "127.0.0.1",
                "AURA_HARNESS_BUS_WORKSPACE": str(ws),
                "AURA_PERF_BUS_WORKSPACE": str(ws),
                "AURA_PERF_BUS_HOST": "0",
                "AURA_PATH": _lib_for(aura),
                # The agent's policy is frozen: the judge measures the
                # candidate's kernel on the real data plane, and a
                # policy that keeps re-applying its own choice would
                # overwrite the judge's setting mid-fold.
                "AURA_REDIS_FROZEN": "1",
                # #5391: the statistical admission is on, the evidence
                # five-tuple is mandatory, and the round must carry a
                # negative control the statistics reject.
                "AURA_BUS_GATE": "1",
                "AURA_BUS_EVIDENCE": "1",
                # The bar: a candidate must beat the baseline by 0.5%
                # after the multiple-comparison haircut. A bar of 1 ppm
                # admits the negative control whenever the probe's noise
                # is positive, which is not a decision.
                "AURA_BUS_GATE_THRESHOLD": "5000",
                "AURA_BUS_GATE_MIN_WINDOWS": "1",
            })

            host_script = redis_dir / "src" / "redis" / "policy_agent.aura"
            if not host_script.is_file():
                report.set("self-adaptation", False, "the redis policy agent is missing")
                report.write(report_dir / "report.json")
                return 1
            # The agent writes its boot guard and pin files into the
            # working directory, so it gets a fresh one: a second run
            # must not trip the guard and skip the boot.
            agent_cwd = Path(tempfile.mkdtemp(prefix="joint-agent-"))
            shutil.copytree(redis_dir / "src", agent_cwd / "src")
            agent = subprocess.Popen(
                [aura, str(host_script)], env=env, cwd=str(agent_cwd),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True)
            # The agent's output is read on a thread: the "bus mode on"
            # line and the grant token arrive while the lane is busy.
            agent_lines: list[str] = []
            reader = threading.Thread(target=_drain, args=(agent, agent_lines), daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 60
                ready = False
                while time.monotonic() < deadline:
                    if any("bus mode on" in line for line in agent_lines):
                        ready = True
                        break
                    time.sleep(0.1)
                if not ready:
                    report.set("self-adaptation", False,
                               "the redis agent did not open the workspace bus")
                    (report_dir / "agent.log").write_text("".join(agent_lines))
                    report.write(report_dir / "report.json")
                    return 1

                # The proposer: perf attaches (caps 7, no keep bit) and
                # proposes a candidate with the evidence bound.
                propose = perf_dir / "scripts" / "joint_propose.aura"
                if not propose.is_file():
                    report.set("self-adaptation", False, "the joint proposer script is missing")
                    report.write(report_dir / "report.json")
                    return 1
                # The proposer holds its session open: a disconnect
                # withdraws the pending trial, so the worldline must
                # stay alive until the judge has decided.
                proposer = subprocess.Popen(
                    [aura, str(propose)], env=env, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                propose_lines: list[str] = []
                reader = threading.Thread(target=_drain, args=(proposer, propose_lines),
                                          daemon=True)
                reader.start()
                worldline = -1
                control_worldline = 0
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline and worldline < 0:
                    for line in list(propose_lines):
                        if line.startswith("wl="):
                            parts = line.strip().split("|")
                            worldline = int(parts[0].split("=")[1])
                            for part in parts:
                                if part.startswith("control="):
                                    control_worldline = int(part.split("=")[1])
                            break
                    time.sleep(0.1)
                (report_dir / "propose.log").write_text("".join(propose_lines))
                if worldline < 0:
                    proposer.terminate()
                    report.set("self-adaptation", False,
                               "the proposer did not open a worldline")
                    report.set("hidden-net-benefit", False, "no candidate was proposed")
                    report.set("no-false-commit", False, "no candidate was proposed")
                    report.set("replayable", False, "no candidate was proposed")
                    report.write(report_dir / "report.json")
                    return 1
                report.notes.append(f"the proposer opened worldline {worldline}")

                # The host grants the judge a scoped keep for every
                # pending trial; the lane reads the tokens and hands them
                # over. Each token is scoped to one worldline.
                deadline = time.monotonic() + 90
                grants: dict[int, str] = {}
                needed = {worldline}
                if control_worldline:
                    needed.add(control_worldline)
                while time.monotonic() < deadline and not needed.issubset(grants):
                    for line in agent_lines:
                        if "bus grant" in line and "token=" in line and "wl=" in line:
                            wl = int(line.split("wl=", 1)[1].split(" ")[0])
                            grants[wl] = line.split("token=", 1)[1].strip()
                    time.sleep(0.1)
                # The progress so far: written before the judge runs so a
                # stalled lane leaves its trace.
                (report_dir / "agent.log").write_text("".join(agent_lines))
                (report_dir / "propose.log").write_text("".join(propose_lines))
                report.notes.append(f"grants: {sorted(grants)}")
                report.notes.append(f"control worldline: {control_worldline!r}")
                grant_token = grants.get(worldline, "")
                if not grant_token:
                    report.set("self-adaptation", False,
                               "the host granted no scoped keep for the candidate")
                    report.set("hidden-net-benefit", False, "the judge had no grant")
                    report.set("no-false-commit", False, "the judge had no grant")
                    report.set("replayable", False, "the judge had no grant")
                    (report_dir / "agent.log").write_text("".join(agent_lines))
                    report.write(report_dir / "report.json")
                    return 1

                # The judge: the real aura-harness process decides. The
                # metric vector it evaluates the candidate under is the
                # live one the load phases left behind (the counters are
                # cumulative, so the ratio the candidate reads is the
                # workload's regime), and the probe itself runs on the
                # quiet server: a probe that fights the workload's own
                # churn measures nothing.
                judged, jout = _harness_judge(
                    harness_dir, ws, worldline, grant_token, aura, env, port,
                    baseline_policy, host, control_worldline,
                    grants.get(control_worldline, ""))
                (report_dir / "judge.json").write_text(jout + "\n")
                kept = bool(judged.get("judge", {}).get("verdict") == "KEEP")
                # The self-adaptation: the kept policy reaches the live
                # data plane without a restart — the server's eviction
                # kernel changes because the host's choose-fn changed.
                # Keep a little traffic on the server while we wait: the
                # candidate's choose-fn reads the tick's delta, and a
                # completely quiet server reports zero deltas, so even a
                # correctly applied policy would pick the baseline. The
                # judge already ran against the quiet server, so this
                # probe cannot pollute its measurements.
                verdict = judged.get("judge") or {}
                before = _live_policy(port)
                after = before
                with BackgroundLoad(port):
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        after = _live_policy(port)
                        if after != before:
                            break
                        time.sleep(0.2)
                report.set("self-adaptation", kept and after != before,
                           f"the kept policy is live (evict {before} -> {after})"
                           if kept and after != before else
                           ("the judge did not keep: {} {}".format(
                               verdict.get("reason", "?"), verdict.get("message", "")).strip()
                            if not kept else
                            f"the kept policy never reached the live plane (evict {before} -> {after})"))

                # The reproduction package: the verdict must reproduce
                # offline, with no coordinator and no live bus.
                repro = judged.get("repro") or {}
                report.notes.append("repro: {}".format(repro))
                report.notes.append("gate verdicts: candidate={} control={}".format(
                    (judged.get("gate") or {}).get("verdict"),
                    (judged.get("control_gate") or {}).get("verdict")))
                packages = report_dir / "packages.jsonl"
                packages.write_text((repro.get("json") or "") + "\n")
                if repro.get("json"):
                    rc2, out2 = _run([aura, "bus-repro", str(packages)], env, timeout=60)
                    (report_dir / "repro.log").write_text(out2)
                    report.set("replayable", rc2 == 0,
                               "the verdict reproduces offline" if rc2 == 0
                               else "the offline re-run disagreed")
                else:
                    report.set("replayable", False, "no reproduction package")

                # The held-out net benefit: the judge measured the kept
                # policy against the pre-switch baseline on the hidden
                # folds the proposer never saw.
                measured = judged.get("heldout") or {}
                benefit = int(measured.get("window") or 0)
                report.set("hidden-net-benefit", benefit > 0,
                           f"held-out net benefit {benefit} ppm")
                # The measurement itself, so a failing night says why.
                heldout = judged.get("heldout") or {}
                after = _info(port)
                report.notes.append(
                    "server after the probe: used={} evicted={} keys={}".format(
                        after.get("used_memory"), after.get("evicted"), after.get("keys")))
                report.notes.append(
                    "held-out: baseline={} candidate={} control={} windows={} control-windows={}".format(
                        (heldout.get("candidate") or {}).get("baseline"),
                        (heldout.get("candidate") or {}).get("candidate"),
                        (heldout.get("control") or {}).get("candidate"),
                        heldout.get("windows"), heldout.get("control_windows")))

                # No false commit: the round's negative control was
                # refused by the coordinator, so a known-harmful candidate
                # cannot land.
                ctrl = judged.get("control_judge") or {}
                refused = bool(ctrl) and not ctrl.get("ok", False)
                report.set("no-false-commit", refused,
                           f"the negative control was refused ({ctrl.get('reason', 'refused')})"
                           if refused else
                           "the negative control was not refused")
                (report_dir / "agent.log").write_text("".join(agent_lines))
            finally:
                # The proposer releases its trial: the worldline ends
                # with the judge, not before it.
                try:
                    proposer.stdin.write("release\n")
                    proposer.stdin.flush()
                    proposer.wait(timeout=10)
                except Exception:
                    proposer.terminate()
                try:
                    agent.stdin.close()
                except Exception:
                    pass
                agent.terminate()
                try:
                    agent.wait(timeout=10)
                except Exception:
                    agent.kill()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()

    report.write(report_dir / "report.json")
    missing = [name for name in CRITERIA if name not in report.criteria]
    if missing:
        report.notes.append(f"criteria not measured: {', '.join(missing)}")
        return 1
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
