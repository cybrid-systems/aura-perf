#!/bin/sh
# Print one pid whose /proc/<pid>/maps names this shared object.
# The argument is a soname (libaura_redis_core.so), not a shell snippet.
set -eu
name=${1:-}
case $name in
  ''|*[!A-Za-z0-9._+-]*)
    exit 1
    ;;
esac
case $name in
  *.so|*.so.*)
    ;;
  *)
    exit 1
    ;;
esac
for maps in /proc/[0-9]*/maps; do
  [ -r "$maps" ] || continue
  if grep -F -q -- "$name" "$maps" 2>/dev/null; then
    pid=${maps#/proc/}
    pid=${pid%/maps}
    printf '%s\n' "$pid"
    exit 0
  fi
done
exit 1
