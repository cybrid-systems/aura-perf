#!/bin/sh
# bcc cachestat page-cache summary as values.
#
#   aura-perf cachestat --file cachestat.txt
#   aura-perf cachestat --seconds N
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
  AURA_PERF_CACHESTAT_FILE="$1" AURA_PERF_CACHESTAT_TOOL="$2" \
    "$AURA" --preset dev --grant exec "$ROOT/scripts/cachestat-parse.aura"
}

if [ -n "$file" ]; then
  [ -f "$file" ] || { echo "cachestat: no such file: $file" >&2; exit 2; }
  parse "$file" file
  exit $?
fi

cs=${CACHESTAT_BIN:-}
if [ -z "$cs" ]; then
  cs=$(command -v cachestat 2>/dev/null || true)
fi
if [ -z "$cs" ] || [ "$cs" = "none" ]; then
  echo "cachestat unavailable reason=no-bcc command=\"aura-perf doctor --install\" fallback=check"
  exit 3
fi

mkdir -p "$ROOT/out"
out="$ROOT/out/cachestat.txt"
log="$ROOT/out/cachestat.log"
set +e
timeout -s INT "$seconds" "$cs" 1 1 >"$out" 2>"$log"
rc=$?
set -e
if ! grep -q 'HITS' "$out"; then
  if grep -Eqi 'permission|not permitted|operation not permitted|requires root' "$log"; then
    echo "cachestat blocked reason=permission command=\"sudo -v\" fallback=check"
    exit 4
  fi
  echo "cachestat failed rc=$rc log=$log" >&2
  tail -5 "$log" >&2 || true
  exit 1
fi
parse "$out" bcc
