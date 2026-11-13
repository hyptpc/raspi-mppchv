#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [[ -n "${HV_PYTHON:-}" ]]; then
    DB_PYTHON="$HV_PYTHON"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    DB_PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$HOME/.venv/bin/python" ]]; then
    DB_PYTHON="$HOME/.venv/bin/python"
else
    DB_PYTHON=python3
fi
exec "$DB_PYTHON" -m modules.db_unlock "$@"
