#!/bin/sh
# aura-perf - one entry point.
#
# The installed command is bin/aura-perf (`aura-perf install` links it into
# ~/.local/bin). This wrapper keeps `./run.sh <verb>` working in a checkout.
set -eu
cd "$(dirname "$0")"
exec sh bin/aura-perf "$@"
