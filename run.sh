#!/usr/bin/env bash
# JobHunt launcher (macOS 12+ and Linux).
#
#   chmod +x run.sh            # first time only
#   ./run.sh                   # start the web UI (opens http://127.0.0.1:8765)
#   ./run.sh --port 9000       # extra args are passed straight to `agent.py ui`
#
# First time here? Run ./setup.sh once, then come back.
# Closing this terminal (Ctrl+C) stops the server.
# Uses .venv/bin/python when setup.sh created one (PEP 668 Linux systems).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

[ -f "$REPO_ROOT/agent.py" ] || { echo "agent.py not found — run this script from the JobHunt project folder." >&2; exit 1; }

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    exec "$REPO_ROOT/.venv/bin/python" agent.py ui "$@"
fi
command -v python3 >/dev/null 2>&1 || { echo "python3 not found — run ./setup.sh first." >&2; exit 1; }
exec python3 agent.py ui "$@"
