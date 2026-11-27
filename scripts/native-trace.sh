#!/bin/sh
# sched_switch trace as values.
#
#   aura-perf trace --file trace.txt
#   aura-perf trace --seconds N
#
# The first form only parses text. The second enables tracefs
# sched_switch, samples for N seconds, restores the previous state, and
# parses the trace. It needs a mounted tracefs and write permission.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AURA=${AURA_BIN:-aura}
seconds=1
file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --file) file=${2:-}; shift 2 ;;
    --seconds) seconds=${2:-}; shift 2 ;;
    *) break ;;
  esac
done

parse() {
  AURA_PERF_TRACE_FILE="$1" AURA_PERF_TRACE_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/trace-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "trace: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi

root=${AURA_PERF_TRACEFS:-/sys/kernel/tracing}
if [ ! -d "$root" ]; then
  root=/sys/kernel/debug/tracing
fi
if [ ! -d "$root" ]; then
  echo "trace unavailable reason=tracefs-not-mounted command=\"sudo mount -t tracefs tracefs /sys/kernel/tracing\" fallback=perf-sched"
  exit 3
fi
if [ ! -w "$root/tracing_on" ] || [ ! -w "$root/events/sched/sched_switch/enable" ] || [ ! -w "$root/trace" ]; then
  echo "trace blocked reason=permission command=\"sudo -v\" fallback=perf-sched"
  exit 4
fi

on_old=$(cat "$root/tracing_on" 2>/dev/null || echo 0)
en_old=$(cat "$root/events/sched/sched_switch/enable" 2>/dev/null || echo 0)
cleanup() {
  echo "$on_old" > "$root/tracing_on" 2>/dev/null || true
  echo "$en_old" > "$root/events/sched/sched_switch/enable" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${AURA_PERF_TRACE_KEEP:-0}" != "1" ]; then
  : > "$root/trace"
fi
echo 1 > "$root/events/sched/sched_switch/enable"
echo 1 > "$root/tracing_on"
sleep "$seconds"
echo 0 > "$root/tracing_on"
echo 0 > "$root/events/sched/sched_switch/enable"

mkdir -p "$ROOT/out"
cp "$root/trace" "$ROOT/out/trace.txt"
parse "$ROOT/out/trace.txt" tracefs
