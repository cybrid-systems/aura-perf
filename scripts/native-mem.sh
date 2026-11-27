#!/bin/sh
# perf mem sample distribution as values.
#
#   aura-perf mem --file mem.txt
#   aura-perf mem -- COMMAND [ARGS...]
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
  AURA_PERF_MEM_FILE="$1" AURA_PERF_MEM_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/mem-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "mem: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi
if [ $# -eq 0 ]; then
  echo "mem: usage: aura-perf mem --file FILE | aura-perf mem -- COMMAND [ARGS...]" >&2
  exit 2
fi

perf=${PERF_BIN:-}
if [ -z "$perf" ]; then
  perf=$(command -v perf 2>/dev/null || true)
fi
if [ -z "$perf" ] || [ "$perf" = "none" ]; then
  echo "mem unavailable reason=no-perf command=\"aura-perf doctor --install\" fallback=profile"
  exit 3
fi

mkdir -p "$ROOT/out"
data="$ROOT/out/mem.data"
txt="$ROOT/out/mem.txt"
log="$ROOT/out/mem.log"

set +e
"$perf" mem record -o "$data" -- "$@" >"$log" 2>&1
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  if grep -Eqi 'permission|not permitted|paranoid|unsupported' "$log"; then
    echo "mem blocked reason=permission command=\"sudo sysctl -w kernel.perf_event_paranoid=2\" fallback=profile"
    exit 4
  fi
  echo "mem record failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi

set +e
"$perf" mem report --stdio --sort symbol -i "$data" >"$txt" 2>"$ROOT/out/mem-report.err"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "mem report failed rc=$rc log=$ROOT/out/mem-report.err" >&2
  exit 1
fi
parse "$txt" perf
