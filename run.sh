#!/bin/sh
# One entry point. No virtualenv, no API key, no config file.
#   ./run.sh            same as autotune
#   ./run.sh help
#   ./run.sh recheck
#   ./run.sh sysinfo
#   ./run.sh check
#   ./run.sh test
#
# Exit codes: autotune is 0 only when the verdict says intend-met=1.
# recheck with no out/evidence.json is non-zero. An unknown verb is
# non-zero. help, sysinfo, and check stay 0.
set -eu
cd "$(dirname "$0")"
if [ -z "${AURA_BIN:-}" ]; then
  if command -v aura >/dev/null 2>&1; then
    AURA_BIN=$(command -v aura)
  elif [ -x "$HOME/aura/bin/aura" ]; then
    AURA_BIN=$HOME/aura/bin/aura
  else
    echo "aura is not on PATH. Install Aura v0.2.0 and set AURA_BIN." >&2
    exit 1
  fi
  export AURA_BIN
fi
export AURA_SANDBOX=off
if [ -z "${AURA_PERF_BUILD:-}" ]; then
  AURA_PERF_BUILD=$("$AURA_BIN" -V 2>&1 | head -n 1 || true)
  export AURA_PERF_BUILD
fi
cmd="${1:-autotune}"
case "$cmd" in
  help|-h|--help)
    exec "$AURA_BIN" --preset dev examples/sum-scan/help.aura
    ;;
  autotune|run)
    set +e
    sh scripts/run-example.sh
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      exit "$rc"
    fi
    sh scripts/verdict-exit.sh out/report.txt
    ;;
  recheck)
    mkdir -p out
    exec "$AURA_BIN" --preset dev examples/sum-scan/recheck.aura
    ;;
  sysinfo)
    mkdir -p out
    exec "$AURA_BIN" --preset dev --grant exec examples/sum-scan/sysinfo.aura
    ;;
  check)
    mkdir -p out
    exec "$AURA_BIN" --preset dev --grant exec examples/sum-scan/check.aura
    ;;
  test)
    # Probe first so a named-let regression is named, then run every
    # test anyway. A real assertion failure is still a failure.
    set +e
    "$AURA_BIN" --preset dev tests/runtime_probe.aura >/tmp/aura-perf-probe.out 2>/tmp/aura-perf-probe.err
    probe=$?
    "$AURA_BIN" test
    rc=$?
    sh tests/exit_test.sh
    exit_rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
      echo "aura-perf: aura test failed." >&2
      echo "aura build: ${AURA_PERF_BUILD:-unknown}" >&2
      echo "supported: Aura v0.2.0 (nightly cf7353373)" >&2
      if [ "$probe" -ne 0 ]; then
        echo "named-let reentrancy probe failed. Upstream: https://github.com/cybrid-systems/aura/issues/5116" >&2
        echo "An index-out-of-bounds error or a parser golden mismatch on this build is that regression, not an aura-perf parser bug." >&2
        cat /tmp/aura-perf-probe.err >&2 || true
        cat /tmp/aura-perf-probe.out >&2 || true
      fi
    fi
    if [ "$rc" -ne 0 ]; then
      exit "$rc"
    fi
    exit "$exit_rc"
    ;;
  *)
    echo "unknown verb: $cmd" >&2
    "$AURA_BIN" --preset dev examples/sum-scan/help.aura
    exit 1
    ;;
esac
