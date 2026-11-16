#!/bin/sh
# Start the BSRN User Dashboard on Linux or macOS.
# The launcher creates a private Python environment (.venv) and installs
# requirements.txt into it on first start.
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python was not found. Install Python 3.10 or newer (Debian/Ubuntu: sudo apt install python3 python3-venv)." >&2
  exit 1
fi

"$PY" "$PROJECT_DIR/scripts/bsrn_launch_dashboard.py" "$@"
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  echo >&2
  echo "Could not start the BSRN User Dashboard. See the messages above." >&2
fi
exit "$STATUS"
