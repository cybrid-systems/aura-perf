#!/usr/bin/env python3
"""aura-perf#30: an agent that cannot boot leaves a report, not a traceback.

The lane used to return from inside a try/finally whose finally touched
`proposer`, which only exists after the agent opened the bus. The
UnboundLocalError hid the real reason (the agent's own log). This test
runs the lane with a dead agent, no real redis server, and checks the
report carries the reason and the log tail.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class DeadServer:
    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def load_lane():
    spec = importlib.util.spec_from_file_location(
        "joint_nightly", ROOT / "scripts" / "joint_nightly.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-joint-absent-"))
    try:
        redis = tmp / "redis"
        (redis / "src" / "redis").mkdir(parents=True)
        (redis / "src" / "redis" / "policy_agent.aura").write_text("")
        harness = tmp / "harness"
        harness.mkdir()
        fake = tmp / "bin" / "aura"
        fake.parent.mkdir()
        fake.write_text(
            "#!/bin/sh\n"
            "echo 'the fake aura has no workspace bus' >&2\n"
            "echo 'the fake agent refused to boot' >&2\n"
            "exit 7\n")
        fake.chmod(0o755)
        report = tmp / "report"

        lane = load_lane()
        env = {
            "AURA_BIN": str(fake),
            "AURA_REDIS_DIR": str(redis),
            "AURA_HARNESS_DIR": str(harness),
            "AURA_PERF_DIR": str(ROOT),
            "JOINT_PORT": "1",
        }
        argv = ["joint_nightly.py", "--report", str(report), "--phases", ""]
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(sys, "argv", argv), \
             mock.patch.object(lane, "_redis_server", return_value=DeadServer()), \
             mock.patch.object(lane, "_ping", return_value=True), \
             mock.patch.object(lane, "_info", return_value={}), \
             mock.patch.object(lane, "_live_policy", return_value="lru"):
            rc = lane.main()

        text = (report / "report.txt").read_text()
        failures = []
        if rc == 0:
            failures.append("the lane returned 0 with a dead agent")
        if "the redis agent did not open the workspace bus" not in text:
            failures.append("the report does not name the missing workspace bus")
        if "agent.log: the fake agent refused to boot" not in text:
            failures.append("the report does not carry the agent log tail")
        if "Traceback" in text:
            failures.append("the report carries a traceback")
        if failures:
            print("FAIL joint agent absent: " + "; ".join(failures))
            print(text)
            return 1
        print("ok joint agent absent: the report carries the reason and the log tail")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
