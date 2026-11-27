#!/bin/sh
# perf sched wakeup latency as values.
#
#   aura-perf sched --file out/sched-latency.txt
#   aura-perf sched -- COMMAND [ARGS...]
#
# The second form records with perf sched record, so it needs perf and the
# perf_event permission. The first form only parses text that already exists.
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
  AURA_PERF_SCHED_FILE="$1" AURA_PERF_SCHED_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/sched-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "sched: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi

if [ $# -eq 0 ]; then
  echo "sched: usage: aura-perf sched --file FILE | aura-perf sched -- COMMAND [ARGS...]" >&2
  exit 2
fi

perf=${PERF_BIN:-}
if [ -z "$perf" ]; then
  perf=$(command -v perf 2>/dev/null || true)
fi
if [ -z "$perf" ] || [ "$perf" = "none" ]; then
  echo "sched unavailable reason=no-perf command=\"aura-perf doctor --install\" fallback=schedstat"
  exit 3
fi

mkdir -p "$ROOT/out"
data="$ROOT/out/sched.data"
lat="$ROOT/out/sched-latency.txt"
log="$ROOT/out/sched-record.log"

set +e
"$perf" sched record -o "$data" -- "$@" >"$log" 2>&1
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  if grep -Eqi 'permission|not permitted|paranoid' "$log"; then
    echo "sched blocked reason=permission command=\"sudo sysctl -w kernel.perf_event_paranoid=2\" fallback=schedstat"
    exit 4
  fi
  echo "sched record failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi

set +e
"$perf" sched latency -i "$data" >"$lat" 2>"$ROOT/out/sched-latency.err"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "sched latency failed rc=$rc log=$ROOT/out/sched-latency.err" >&2
  exit 1
fi

printf 'schedtrace command="%s"' "$*"
printf '\n'
parse "$lat" perf
