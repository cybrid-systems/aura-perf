#!/bin/sh
# One entry point. No virtualenv, no API key, no config file.
#   ./run.sh            same as autotune
#   ./run.sh help
#   ./run.sh recheck
#   ./run.sh sysinfo
#   ./run.sh check
#   ./run.sh test
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
cmd="${1:-autotune}"
case "$cmd" in
  help|-h|--help)
    exec "$AURA_BIN" --preset dev examples/sum-scan/help.aura
    ;;
  autotune|run)
    exec sh scripts/run-example.sh
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
    exec "$AURA_BIN" test
    ;;
  *)
    echo "unknown verb: $cmd" >&2
    exec "$AURA_BIN" --preset dev examples/sum-scan/help.aura
    ;;
esac
