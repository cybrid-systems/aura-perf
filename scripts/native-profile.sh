#!/bin/sh
# Native profiling for any process, not just Aura targets.
#
#   aura-perf profile --pid PID [--seconds N] [--out DIR]
#   aura-perf profile [--seconds N] [--out DIR] -- COMMAND [ARGS...]
#
# Requires a usable perf (task-clock support, attach permission). No Aura
# binary, no workspace, no LLM. The text report is out/profile.txt; the
# raw perf data is out/perf.data.
set -eu

seconds=10
pid=""
out="out"
while [ $# -gt 0 ]; do
  case "$1" in
    --pid) pid=${2:-}; shift 2 ;;
    --seconds|-s) seconds=${2:-}; shift 2 ;;
    --out) out=${2:-}; shift 2 ;;
    --) shift; break ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) break ;;
  esac
done

case "$seconds" in ''|*[!0-9]*) echo "aura-perf profile: --seconds must be a positive integer" >&2; exit 2 ;; esac
[ "$seconds" -gt 0 ] || { echo "aura-perf profile: --seconds must be positive" >&2; exit 2; }

perf="${PERF_BIN:-}"
if [ -z "$perf" ]; then
  perf=$(sh "$(dirname "$0")/find-perf.sh" 2>/dev/null || true)
fi
[ -n "$perf" ] || { echo "aura-perf profile: no usable perf on this machine (PERF_BIN, linux-tools)" >&2; exit 1; }

mkdir -p "$out"
data="$out/perf.data"
report="$out/profile.txt"
rm -f "$data"

# Collect. A PID is the useful mode for a server (redis-server, postgres,
# a game core); a command is useful for a batch job that exits.
if [ -n "$pid" ]; then
  [ -r "/proc/$pid" ] || { echo "aura-perf profile: no such pid: $pid" >&2; exit 1; }
  command_line=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
  if ! "$perf" record -F 999 -g -p "$pid" -o "$data" -- sleep "$seconds" >"$out/perf-record.log" 2>&1; then
    echo "aura-perf profile: perf record failed" >&2
    tail -20 "$out/perf-record.log" >&2 || true
    exit 1
  fi
else
  [ $# -gt 0 ] || { echo "aura-perf profile: give --pid PID or -- COMMAND" >&2; exit 2; }
  command_line="$*"
  if ! timeout "$seconds" "$perf" record -F 999 -g -o "$data" -- "$@" >"$out/perf-record.log" 2>&1; then
    rc=$?
    # 124 is the normal timeout for a server/batch command; only a perf
    # failure (no data) is fatal.
    if [ "$rc" -ne 124 ]; then
      echo "aura-perf profile: perf record failed" >&2
      tail -20 "$out/perf-record.log" >&2 || true
      exit 1
    fi
  fi
fi

[ -s "$data" ] || { echo "aura-perf profile: perf produced no samples" >&2; exit 1; }

# Optional counters. Unsupported PMU events are reported, never invented.
counters="$out/perf-counters.txt"
if [ -n "$pid" ]; then
  "$perf" stat -e task-clock,cycles,instructions,cache-misses,context-switches -p "$pid" -- sleep "$seconds" >"$counters" 2>&1 || true
fi

{
  printf 'native-profile\n'
  printf 'pid: %s\n' "${pid:-launched}"
  printf 'command: %s\n' "$command_line"
  printf 'seconds: %s\n' "$seconds"
  printf 'perf: %s\n' "$perf"
  printf 'data: %s\n' "$data"
  printf '\nTop self symbols (perf report, no children):\n'
  "$perf" report --stdio -i "$data" -g none --no-children --sort symbol --percent-limit 0.5 2>/dev/null |
    awk 'BEGIN{print "# overhead  symbol"} /^[[:space:]]*[0-9.]+%/ {print}' |
    head -30
  printf '\nDSO summary:\n'
  "$perf" report --stdio -i "$data" -g none --no-children --sort dso --percent-limit 0.5 2>/dev/null |
    awk 'BEGIN{print "# overhead  dso"} /^[[:space:]]*[0-9.]+%/ {print}' |
    head -20
  if [ -s "$counters" ]; then
    printf '\nCounters:\n'
    cat "$counters"
  fi
} > "$report"

# A tiny machine-readable view for agents; Python is already required by
# the pinned installer.
python3 - "$report" "$out/profile.json" "$data" "${pid:-}" "$seconds" "$command_line" <<'PY'
import json, re, sys
report, dest, data, pid, seconds, cmd = sys.argv[1:7]
top = []
for line in open(report, encoding="utf-8", errors="replace"):
    m = re.match(r"\s*([0-9.]+)%\s+(?:\[[^\]]+\]\s+)?(.*?)\s{2,}.*$", line)
    if m:
        top.append({"overhead_pct": float(m.group(1)), "symbol": m.group(2).strip()})
        if len(top) >= 20:
            break
json.dump({"kind": "native-profile", "pid": pid or None, "seconds": int(seconds),
           "command": cmd, "data": data, "report": report, "top": top},
          open(dest, "w", encoding="utf-8"), indent=2)
PY

printf 'native-profile pid=%s seconds=%s\n' "${pid:-launched}" "$seconds"
printf 'report: %s\n' "$report"
printf 'json:   %s\n' "$out/profile.json"
sed -n '/Top self symbols/,/DSO summary/p' "$report" | sed -n '2,12p'
