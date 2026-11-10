#!/bin/sh
# Print a perf binary that actually runs on this kernel.
# /usr/bin/perf is a wrapper that exits when its package version does not
# match `uname -r`. The versioned binary under /usr/lib/linux-tools still
# talks to a newer kernel for software events.
if [ -n "${PERF_BIN:-}" ] && "$PERF_BIN" --version >/dev/null 2>&1; then
  printf '%s\n' "$PERF_BIN"
  exit 0
fi
for p in /usr/lib/linux-tools/*/perf; do
  if [ -x "$p" ] && "$p" --version >/dev/null 2>&1; then
    printf '%s\n' "$p"
    exit 0
  fi
done
exit 1
