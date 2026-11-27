#!/bin/sh
# bpftrace off-CPU summary for one pid.
#
#   aura-perf offcpu --file offcpu.txt
#   aura-perf offcpu --pid PID [--seconds N]
#
# The live form needs bpftrace and the BPF permission. It prints one value
# line; no stack text is sent to the model.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AURA=${AURA_BIN:-aura}
pid=""
seconds=1
file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pid) pid=${2:-}; shift 2 ;;
    --seconds) seconds=${2:-}; shift 2 ;;
    --file) file=${2:-}; shift 2 ;;
    *) break ;;
  esac
done

parse() {
  AURA_PERF_OFFCPU_FILE="$1" AURA_PERF_OFFCPU_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/offcpu-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "offcpu: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi
if [ -z "$pid" ] || [ "$pid" = "0" ]; then
  echo "offcpu: usage: aura-perf offcpu --pid PID [--seconds N] | --file FILE" >&2
  exit 2
fi

bt=${BPFTRACE_BIN:-}
if [ -z "$bt" ]; then
  bt=$(command -v bpftrace 2>/dev/null || true)
fi
if [ -z "$bt" ] || [ "$bt" = "none" ]; then
  echo "offcpu unavailable reason=no-bpftrace command=\"aura-perf doctor --install\" fallback=trace"
  exit 3
fi

mkdir -p "$ROOT/out"
out="$ROOT/out/offcpu.txt"
log="$ROOT/out/offcpu.log"
script='BEGIN { @total = 0; @max = 0; @samples = 0; }
tracepoint:sched:sched_switch /args->prev_pid == $1 / { @start = nsecs; }
tracepoint:sched:sched_switch /args->next_pid == $1 && @start / { $d = nsecs - @start; @total = @total + $d; if ($d > @max) { @max = $d; } @samples = @samples + 1; delete(@start); }
END { printf("offcpu pid=%d total-ms=%d max-ms=%d samples=%d\n", $1, @total / 1000000, @max / 1000000, @samples); }'

set +e
timeout -s INT "$seconds" "$bt" -q -e "$script" "$pid" >"$out" 2>"$log"
rc=$?
set -e
if ! grep -q '^offcpu ' "$out"; then
  if grep -Eqi 'permission|not permitted|operation not permitted|requires root' "$log"; then
    echo "offcpu blocked reason=permission command=\"sudo -v\" fallback=trace"
    exit 4
  fi
  echo "offcpu failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi
parse "$out" bpftrace
