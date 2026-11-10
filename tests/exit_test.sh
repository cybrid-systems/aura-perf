#!/bin/sh
# Exit codes for ./run.sh. Does not run a full autotune; the autotune
# decision is scripts/verdict-exit.sh, which ./run.sh autotune calls
# when the process itself returns 0.
set -eu
cd "$(dirname "$0")/.."
fail=0

check() {
  name=$1
  want=$2
  shift 2
  set +e
  "$@" >/tmp/aura-perf-exit-out 2>/tmp/aura-perf-exit-err
  got=$?
  set -e
  if [ "$got" -eq "$want" ]; then
    printf 'ok %s exit=%s\n' "$name" "$got"
  else
    printf 'FAIL %s exit=%s want=%s\n' "$name" "$got" "$want" >&2
    cat /tmp/aura-perf-exit-out >&2 || true
    cat /tmp/aura-perf-exit-err >&2 || true
    fail=1
  fi
}

need_out() {
  name=$1
  want=$2
  file=$3
  if grep -qF "$want" "$file"; then
    printf 'ok %s contains %s\n' "$name" "$want"
  else
    printf 'FAIL %s missing %s\n' "$name" "$want" >&2
    cat "$file" >&2 || true
    fail=1
  fi
}

mkdir -p out
bak=""
if [ -f out/evidence.json ]; then
  bak=$(mktemp)
  cp out/evidence.json "$bak"
  rm -f out/evidence.json
fi

check recheck-missing 1 ./run.sh recheck
need_out recheck-hint "recheck needs out/evidence.json" /tmp/aura-perf-exit-out
need_out recheck-hint-cmd "./run.sh autotune" /tmp/aura-perf-exit-out
check unknown-verb 1 ./run.sh recheck-with-a-typo
need_out unknown-verb-msg "unknown verb:" /tmp/aura-perf-exit-err

check help 0 ./run.sh help
check sysinfo 0 ./run.sh sysinfo
check check 0 ./run.sh check

# The installed command: same verbs, and it must work from any directory.
# The repo root is resolved from the script's own path, so a symlink in
# ~/.local/bin runs this checkout.
check cmd-help 0 sh bin/aura-perf help
need_out cmd-help-usage "aura-perf [verb]" /tmp/aura-perf-exit-out
check cmd-unknown 1 sh bin/aura-perf not-a-verb
check cmd-from-elsewhere 0 sh -c "cd / && '$PWD/bin/aura-perf' help"
check cmd-sysinfo-from-elsewhere 0 sh -c "cd / && '$PWD/bin/aura-perf' sysinfo"
# help must not need the aura binary
check cmd-help-no-aura 0 env -u AURA_BIN PATH=/bin:/usr/bin "$PWD/bin/aura-perf" help
check cmd-no-aura 1 env -u AURA_BIN PATH=/bin:/usr/bin "$PWD/bin/aura-perf" sysinfo

# The retired primitive prefixes (Aura v0.2.1 closed the alias window):
# ast: / workspace: / ws: / dirty: / mutation-log: / syntax: / fiber:overlay-
# are unbound now. A library that still calls one dies mid-run, so the
# sources are checked here instead of waiting for that run.
retired=$(grep -rEn '\((ast|workspace|ws|dirty|mutation-log|syntax|fiber:overlay-)[a-z-]+' \
            lib examples 2>/dev/null | grep -v '^\s*;' || true)
if [ -z "$retired" ]; then
  printf 'ok no-retired-prefix exit=0\n'
else
  printf 'FAIL retired-prefix exit=1\n' >&2
  printf '%s\n' "$retired" >&2
  printf 'these primitives are unbound on Aura v0.2.1 and later; use the\n' >&2
  printf 'mutate verb (mutate :snapshot / :restore) or (query :op ...)\n' >&2
  fail=1
fi

printf '%s\n' 'verdict intend-met=1 KEEP=3 ROLLBACK=6 speedup-x=81.25 (325ms->4ms n=5 spread=120->0ms)' \
  > /tmp/aura-perf-verdict-met.txt
printf '%s\n' 'verdict intend-met=0 KEEP=0 ROLLBACK=1 speedup-x=1.00 (10ms->10ms n=5 spread=0->0ms)' \
  > /tmp/aura-perf-verdict-unmet.txt
printf '%s\n' 'verdict intend-met=10 KEEP=1 ROLLBACK=0 speedup-x=1.10 (11ms->10ms n=5 spread=1->0ms)' \
  > /tmp/aura-perf-verdict-ten.txt
check verdict-met 0 sh scripts/verdict-exit.sh /tmp/aura-perf-verdict-met.txt
check verdict-unmet 1 sh scripts/verdict-exit.sh /tmp/aura-perf-verdict-unmet.txt
need_out verdict-unmet-msg "intend not met:" /tmp/aura-perf-exit-err
check verdict-ten 1 sh scripts/verdict-exit.sh /tmp/aura-perf-verdict-ten.txt
check verdict-missing 1 sh scripts/verdict-exit.sh /tmp/aura-perf-no-such-report.txt
need_out verdict-missing-msg "wrote no verdict" /tmp/aura-perf-exit-err

# A saved run with samples still exits 0. The verdict line carries the medians.
cat > out/evidence.json <<'EOF'
{"before-ms":100,"after-ms":40,"before-samples":[80,90,100,120,130],"after-samples":[38,40,40,40,42],"cct":{"kind":"perf-cct","nodes":[]},"candidates":[{"id":"linear-scan","target":"bench-kernel","status":"ok","checksum-ok":1,"mismatches":0,"heldout-ms":40,"fidelity":"held-out","live-unchanged":1}],"class":"","hot-node":"","prefix":[],"memory":[]}
EOF
check recheck-present 0 ./run.sh recheck
need_out recheck-context "speedup-x=2.50 (100ms->40ms n=5 spread=50->4ms)" /tmp/aura-perf-exit-out

if [ -n "$bak" ]; then
  mv "$bak" out/evidence.json
else
  rm -f out/evidence.json
fi

if [ "$fail" -ne 0 ]; then
  echo "exit-code tests failed" >&2
  exit 1
fi
echo "exit-code tests passed"
exit 0
