#!/bin/sh
# One command:
#   curl -fsSL https://raw.githubusercontent.com/cybrid-systems/aura-perf/main/install.sh | sh
#
# Installs the pinned Aura nightly and links `aura-perf` into
# ~/.local/bin. Re-running is safe. Set AURA_PERF_DIR to choose the copy,
# PREFIX to choose the bin directory, or AURA_BIN to use an existing
# nightly instead of downloading one.
set -eu

here=$(CDPATH= cd -- "$(dirname "$0")" 2>/dev/null && pwd || true)
root="${AURA_PERF_DIR:-$HOME/.local/share/aura-perf}"

if [ -n "$here" ] && [ -f "$here/bin/aura-perf" ]; then
  root=$here
elif [ ! -f "$root/bin/aura-perf" ]; then
  mkdir -p "$(dirname "$root")"
  printf 'installing aura-perf into %s...\n' "$root"
  if [ -d "$root/.git" ]; then
    git -C "$root" pull --ff-only
  else
    git clone --depth 1 https://github.com/cybrid-systems/aura-perf.git "$root"
  fi
fi

if [ -z "${AURA_BIN:-}" ] && ! (command -v aura >/dev/null 2>&1 && aura --version 2>/dev/null | grep -q nightly); then
  AURA_VERSION=nightly sh "$root/scripts/install-aura.sh" >/dev/null
fi
AURA_VERSION=nightly sh "$root/bin/aura-perf" install
printf '\nready: aura-perf\n'
