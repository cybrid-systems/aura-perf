#!/bin/sh
# Run the sum-scan example from the repository root.
# AURA_SANDBOX=off is required so evo:trial can mutate the forked worldline.
# preset=dev alone leaves the sandbox restricted, and a child workspace then
# refuses mutate:rebind with cow-refused.
set -eu
cd "$(dirname "$0")/.."
mkdir -p out/jobs out/trials
export AURA_SANDBOX=off
export AURA_EVO_LOG="${AURA_EVO_LOG:-$PWD/out/evo.jsonl}"
exec aura --preset dev --grant exec examples/sum-scan/main.aura
