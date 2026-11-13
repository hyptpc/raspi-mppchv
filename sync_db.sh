#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [[ -n "${HV_PYTHON:-}" ]]; then
    SYNC_PYTHON="$HV_PYTHON"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    SYNC_PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$HOME/.venv/bin/python" ]]; then
    SYNC_PYTHON="$HOME/.venv/bin/python"
else
    SYNC_PYTHON=python3
fi
exec "$SYNC_PYTHON" -m modules.db_sync "$@"
