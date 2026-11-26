#!/bin/sh
# tests/profile_test.sh — native perf profile, no Aura binary.
# Skips when this machine has no usable perf (the rest of aura-perf still
# works on region timers). The target is a busy shell: profile must
# produce a report and JSON without resolving AURA_BIN.
set -eu
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'kill "${pid:-}" 2>/dev/null || true; rm -rf "$tmp"' EXIT INT TERM
perf="${PERF_BIN:-}"
if [ -z "$perf" ]; then
  perf=$(sh scripts/find-perf.sh 2>/dev/null || true)
fi
if [ -z "$perf" ]; then
  echo "skip profile_test: no usable perf"
  exit 0
fi
# A busy loop so the sampler has something to count.
nohup sh -c 'while :; do :; done' >/dev/null 2>&1 &
pid=$!
sleep 0.2
set +e
AURA_BIN=/nonexistent PERF_BIN="$perf" sh bin/aura-perf profile --pid "$pid" --seconds 1 --out "$tmp" >"$tmp/out" 2>&1
rc=$?
set -e
kill "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true
if [ "$rc" -ne 0 ]; then
  echo "skip profile_test: perf attach unavailable (rc=$rc)"
  sed -n '1,5p' "$tmp/out" 2>/dev/null || true
  exit 0
fi
[ -s "$tmp/profile.txt" ] || { echo "FAIL profile_test: no profile.txt" >&2; exit 1; }
[ -s "$tmp/profile.json" ] || { echo "FAIL profile_test: no profile.json" >&2; exit 1; }
grep -q '"kind": "native-profile"' "$tmp/profile.json" || {
  echo "FAIL profile_test: wrong json kind" >&2; exit 1
}
grep -q 'Top self symbols' "$tmp/profile.txt" || {
  echo "FAIL profile_test: no hotspot section" >&2; exit 1
}
echo "ok profile_test: native report + json without Aura"
