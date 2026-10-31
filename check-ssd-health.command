#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=""
if [ -x /usr/bin/python3 ]; then
  PY=/usr/bin/python3
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi
if [ -z "$PY" ]; then
  echo "Python 3 is not on this Mac. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
exec "$PY" "$(dirname "$0")/ssd_health.py" "$@"
