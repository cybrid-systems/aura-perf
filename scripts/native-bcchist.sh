#!/bin/sh
# bcc histogram (runqlat / biolatency) as values.
#
#   aura-perf runqlat --file F | --seconds N
#   aura-perf biolatency --file F | --seconds N
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AURA=${AURA_BIN:-aura}
tool=""
seconds=1
file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tool) tool=${2:-}; shift 2 ;;
    --file) file=${2:-}; shift 2 ;;
    --seconds) seconds=${2:-}; shift 2 ;;
    *) break ;;
  esac
done
if [ -z "$tool" ]; then
  echo "hist: missing --tool" >&2
  exit 2
fi

parse() {
  AURA_PERF_HIST_FILE="$1" AURA_PERF_HIST_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/bcchist-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "$tool: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi

if [ "$tool" = "runqlat" ]; then
  bin=${RUNQLAT_BIN:-}
else
  bin=${BIOLATENCY_BIN:-}
fi
if [ -z "$bin" ]; then
  bin=$(command -v "$tool" 2>/dev/null || true)
fi
if [ -z "$bin" ] || [ "$bin" = "none" ]; then
  echo "$tool unavailable reason=no-bcc command=\"aura-perf doctor --install\" fallback=check"
  exit 3
fi

mkdir -p "$ROOT/out"
out="$ROOT/out/$tool.txt"
log="$ROOT/out/$tool.log"
set +e
timeout -s INT "$seconds" "$bin" 1 1 >"$out" 2>"$log"
rc=$?
set -e
if ! grep -q 'count' "$out"; then
  if grep -Eqi 'permission|not permitted|operation not permitted|requires root' "$log"; then
    echo "$tool blocked reason=permission command=\"sudo -v\" fallback=check"
    exit 4
  fi
  echo "$tool failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi
parse "$out" bcc
