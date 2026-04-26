#!/usr/bin/env bash
# ============================================================================
#  DBD Auto Skill Check - Start (Linux / macOS)
#  --------------------------------------------------------------------------
#  Launches the Flask UI on http://127.0.0.1:7860 using the venv created by
#  setup.sh, then opens the page in your default browser.
#
#  If you haven't run setup.sh yet, this script will tell you to.
# ============================================================================

set -u

cd "$(dirname "$0")"

VENV_PY=".venv/bin/python"
HOST="127.0.0.1"
PORT="7860"
URL="http://${HOST}:${PORT}"

if [ ! -x "$VENV_PY" ]; then
    echo
    echo "[ERROR] Virtual environment not found."
    echo "        Run ./setup.sh first to install dependencies."
    echo
    exit 1
fi

if [ ! -f "app_flask.py" ]; then
    echo
    echo "[ERROR] app_flask.py not found in this directory."
    echo "        Make sure start.sh sits next to app_flask.py."
    echo
    exit 1
fi

echo
echo "============================================================================"
echo "  Starting DBD Auto Skill Check on ${URL}"
echo "============================================================================"
echo

# Pick a browser opener (Linux: xdg-open; macOS: open). Skip silently if neither
# is available - the user can just paste the URL by hand.
OPENER=""
if command -v xdg-open >/dev/null 2>&1; then
    OPENER="xdg-open"
elif command -v open >/dev/null 2>&1; then
    OPENER="open"
fi

if [ -n "$OPENER" ]; then
    ( sleep 3 && "$OPENER" "$URL" >/dev/null 2>&1 ) &
fi

"$VENV_PY" app_flask.py --host "$HOST" --port "$PORT"
EXITCODE=$?

echo
echo "Server exited with code ${EXITCODE}."
exit "$EXITCODE"
