#!/bin/sh
# Re-score the last autotune against the current intend and strategy genes.
set -eu
cd "$(dirname "$0")/.."
exec sh run.sh recheck
