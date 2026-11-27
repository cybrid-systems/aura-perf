#!/bin/sh
# perf c2c cache-line contention summary as values.
#
#   aura-perf c2c --file c2c.txt
#   aura-perf c2c -- COMMAND [ARGS...]
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AURA=${AURA_BIN:-aura}
file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --file) file=${2:-}; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done

parse() {
  AURA_PERF_C2C_FILE="$1" AURA_PERF_C2C_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/c2c-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "c2c: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi
if [ $# -eq 0 ]; then
  echo "c2c: usage: aura-perf c2c --file FILE | aura-perf c2c -- COMMAND [ARGS...]" >&2
  exit 2
fi

perf=${PERF_BIN:-}
if [ -z "$perf" ]; then
  perf=$(command -v perf 2>/dev/null || true)
fi
if [ -z "$perf" ] || [ "$perf" = "none" ]; then
  echo "c2c unavailable reason=no-perf command=\"aura-perf doctor --install\" fallback=profile"
  exit 3
fi

mkdir -p "$ROOT/out"
data="$ROOT/out/c2c.data"
txt="$ROOT/out/c2c.txt"
log="$ROOT/out/c2c.log"

set +e
"$perf" c2c record -o "$data" -- "$@" >"$log" 2>&1
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  if grep -Eqi 'permission|not permitted|paranoid|unsupported' "$log"; then
    echo "c2c blocked reason=permission command=\"sudo sysctl -w kernel.perf_event_paranoid=2\" fallback=profile"
    exit 4
  fi
  echo "c2c record failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi

set +e
"$perf" c2c report --stdio -i "$data" >"$txt" 2>"$ROOT/out/c2c-report.err"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "c2c report failed rc=$rc log=$ROOT/out/c2c-report.err" >&2
  exit 1
fi
parse "$txt" perf
