#!/bin/sh
# Exit 0 when the report verdict says intend-met=1.
# Exit 1 when the intent was not met, or the report is not there.
# intend-met=10 does not count as met: the 1 must end the token.
set -eu
file="${1:-out/report.txt}"
if [ ! -f "$file" ]; then
  echo "autotune wrote no verdict. Expected $file. Re-run: ./run.sh autotune" >&2
  exit 1
fi
line=$(head -n 1 "$file" || true)
case "$line" in
  *intend-met=1\ *|*intend-met=1)
    exit 0
    ;;
esac
echo "intend not met: $line" >&2
exit 1
