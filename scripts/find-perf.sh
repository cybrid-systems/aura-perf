#!/bin/sh
# Print a perf binary that can count task-clock on this kernel.
# /usr/bin/perf from linux-tools-common is a wrapper: it exits when the
# packaged version does not match `uname -r`. A versioned ELF under
# /usr/lib/linux-tools still counts software events on a newer kernel.
usable() {
  [ -n "$1" ] && [ -x "$1" ] && "$1" stat -e task-clock -- true >/dev/null 2>&1
}

if usable "${PERF_BIN:-}"; then
  printf '%s\n' "$PERF_BIN"
  exit 0
fi

# Prefer a real binary over the wrapper. `command -v` is last.
candidates=""
for p in /usr/lib/linux-tools/*/perf /usr/lib/linux-tools/*/*/perf \
         /usr/libexec/perf /usr/bin/perf; do
  candidates="$candidates $p"
done
if command -v perf >/dev/null 2>&1; then
  candidates="$candidates $(command -v perf)"
fi

for p in $candidates; do
  if usable "$p"; then
    printf '%s\n' "$p"
    exit 0
  fi
done
exit 1
