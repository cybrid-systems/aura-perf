#!/usr/bin/env python3
"""aura-perf doctor: readiness is a value, and install/permission are opt-in.

The test puts only the commands the doctor script needs on PATH, so a real
perf on the host cannot leak into the result. It covers: missing perf with
the workspace-probe fallback, a usable perf, a restricted paranoid that
turns into an ask line, an opt-in install that never runs in dry-run, and
an install that refuses to prompt for sudo on a tty-less run.
"""
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


def write_exe(path, body):
    path.write_text(body)
    path.chmod(0o755)


def tool_dir(tmp, perf=None, sudo_ok=True):
    d = Path(tempfile.mkdtemp(prefix="tools-", dir=tmp))
    for name in ("sh", "dirname", "readlink", "sed", "mkdir", "ln", "rm",
                 "cat", "id", "true", "test", "uname", "printf"):
        src = shutil.which(name, path="/usr/bin:/bin")
        if src:
            (d / name).symlink_to(src)
    if perf is not None:
        write_exe(d / "perf", perf)
    write_exe(d / "sudo", """#!/bin/sh
if [ "$1" = "-n" ]; then exit %s; fi
if [ "$1" = "-v" ]; then exit 0; fi
echo "$@" >> "$DOCTOR_SUDO_LOG"
exec "$@"
""" % ("0" if sudo_ok else "1"))
    write_exe(d / "apt-get", """#!/bin/sh
echo "$@" >> "$DOCTOR_APT_LOG"
exit 0
""")
    return d


PERF_OK = """#!/bin/sh
case "$1" in
  stat)
    if [ "$2" = "--help" ]; then exit 0; fi
    exit 0 ;;
  record|sched|c2c|mem) exit 0 ;;
esac
exit 0
"""

PERF_BROKEN = """#!/bin/sh
case "$1" in
  stat)
    if [ "$2" = "--help" ]; then exit 0; fi
    echo "WARNING: perf not found for kernel 7.0; install linux-perf" >&2
    exit 1 ;;
  record|sched|c2c|mem) exit 0 ;;
esac
exit 0
"""

PERF_BLOCKED = """#!/bin/sh
case "$1" in
  stat)
    if [ "$2" = "--help" ]; then exit 0; fi
    echo "permission denied" >&2
    exit 1 ;;
  record|sched|c2c|mem) exit 0 ;;
esac
exit 0
"""

OS_RELEASE = chr(10).join(['PRETTY_NAME="Test Linux"', 'ID=ubuntu', 'ID_LIKE=debian']) + chr(10)


def run(env, args=()):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([str(BIN), "doctor", *args], cwd=ROOT, env=e,
                          capture_output=True, text=True, timeout=90)


def has(out, needle):
    return needle in out


def main():
    aura = resolve_aura()
    if not aura:
        print("skip doctor_test: no aura binary")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="aura-perf-doctor-"))
    osr = tmp / "os-release"
    osr.write_text(OS_RELEASE)
    apt_log = tmp / "apt.log"
    sudo_log = tmp / "sudo.log"
    fail = 0

    def check(name, ok, detail=""):
        nonlocal fail
        if ok:
            print("ok doctor:", name)
        else:
            print("FAIL doctor:", name)
            if detail:
                print(detail[:1200])
            fail += 1

    base = {"AURA_BIN": str(aura), "AURA_PERF_DOCTOR_OS_RELEASE": str(osr),
            "DOCTOR_APT_LOG": str(apt_log), "DOCTOR_SUDO_LOG": str(sudo_log)}

    # 1. no perf: degraded, but the workspace probes are named.
    env_missing = dict(base, PATH=str(tool_dir(tmp, perf=None)))
    apt_log.unlink(missing_ok=True)
    r = run(env_missing)
    check("missing perf is degraded, not a failure", "doctor tier=degraded" in r.stdout, r.stdout + r.stderr)
    check("the workspace probe is the fallback", "source auto-probe state=ok" in r.stdout, r.stdout)
    check("the missing pmu package and exact command are printed",
          'install group=pmu missing=perf optional=no command="sudo apt-get install -y linux-perf"' in r.stdout,
          r.stdout)
    check("dry-run runs no package manager", not apt_log.exists(), str(apt_log))
    check("a dry-run doctor exits 0", r.returncode == 0, f"rc={r.returncode}")
    check("a passwordless sudo is named for the install path",
          "sudo state=passwordless" in r.stdout, r.stdout)
    r_strict = run(env_missing, args=("--strict",))
    check("strict exits 4 when the pmu is missing", r_strict.returncode == 4,
          f"rc={r_strict.returncode}")

    # 2. a usable perf: full tier, no pmu install line.
    env_full = dict(base, PATH=str(tool_dir(tmp, perf=PERF_OK)))
    r = run(env_full)
    check("a usable perf is the full tier", "doctor tier=full" in r.stdout, r.stdout + r.stderr)
    check("pmu is present and wired", "source pmu state=ok" in r.stdout and "wired=yes" in r.stdout, r.stdout)
    check("nothing asks to install perf", "install group=pmu" not in r.stdout, r.stdout)
    r_strict = run(env_full, args=("--strict",))
    check("strict is 0 when the pmu is ready", r_strict.returncode == 0,
          f"rc={r_strict.returncode}")

    # 2b. the smoke test is the truth: a high sysctl number alone does not
    # create an ask when perf actually opened a counter.
    r = run(dict(env_full, AURA_PERF_DOCTOR_PARANOID="4"))
    check("a working smoke test wins over a high paranoid",
          "perm perf-events state=ok paranoid=4" in r.stdout
          and "ask permission name=perf-events" not in r.stdout, r.stdout)

    # 3. a permission failure under a high paranoid: the ask line carries
    # the exact sysctl and its fallback.
    env_restricted = dict(base, PATH=str(tool_dir(tmp, perf=PERF_BLOCKED)),
                          AURA_PERF_DOCTOR_PARANOID="4")
    r = run(env_restricted)
    check("restricted perf events are named",
          "perm perf-events state=restricted paranoid=4" in r.stdout, r.stdout)
    check("the sysctl and its fallback are an ask line",
          "ask permission name=perf-events" in r.stdout
          and "kernel.perf_event_paranoid=2" in r.stdout
          and "fallback=region-timers" in r.stdout, r.stdout)

    # 4. blocked perf: the smoke test's reason is preserved.
    env_blocked = dict(base, PATH=str(tool_dir(tmp, perf=PERF_BLOCKED)))
    r = run(env_blocked)
    check("a blocked perf is not reported as present",
          "tool perf state=blocked" in r.stdout and "permission denied" in r.stdout, r.stdout)
    check("a permission failure is not an install problem",
          "install group=pmu" not in r.stdout and "perm perf-events state=permission" in r.stdout,
          r.stdout)

    # 4b. a version-wrapper failure is an install problem, with the same
    # exact package command as a missing binary.
    env_broken = dict(base, PATH=str(tool_dir(tmp, perf=PERF_BROKEN)))
    r = run(env_broken)
    check("a broken perf still names the package to install",
          "tool perf state=blocked" in r.stdout
          and "perm perf-events state=tool-blocked" in r.stdout
          and 'install group=pmu missing=perf optional=no command="sudo apt-get install -y linux-perf"' in r.stdout,
          r.stdout)

    # 5. opt-in install: only the selected group runs; sudo never prompts.
    apt_log.unlink(missing_ok=True)
    env_install = dict(env_missing, AURA_PERF_DOCTOR_EXEC="1",
                       AURA_PERF_DOCTOR_GROUPS="pmu")
    r = run(env_install)
    check("the selected group is installed", "install ok group=pmu" in r.stdout, r.stdout + r.stderr)
    log = apt_log.read_text() if apt_log.exists() else ""
    check("the recorded command is the apt install", "install -y linux-perf" in log, log)

    # 6. no tty and no passwordless sudo: refuse, do not hang.
    apt_log.unlink(missing_ok=True)
    env_nosudo = dict(base, PATH=str(tool_dir(tmp, perf=None, sudo_ok=False)),
                      AURA_PERF_DOCTOR_EXEC="1", AURA_PERF_DOCTOR_GROUPS="pmu")
    r = run(env_nosudo)
    check("a password-protected sudo is named before --install",
          "sudo state=needs-password" in r.stdout, r.stdout)
    check("sudo without a tty is blocked, not prompted",
          "install blocked" in r.stdout and "reason=sudo-needs-tty" in r.stdout, r.stdout)
    check("a blocked install exits 4", r.returncode == 4, f"rc={r.returncode}")
    check("a blocked install ran no package manager", not apt_log.exists(), str(apt_log))

    shutil.rmtree(tmp, ignore_errors=True)
    return fail


if __name__ == "__main__":
    sys.exit(main())
