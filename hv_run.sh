#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
SESSION_NAME=hv
TMUX_PATH=tmux

CONFIG=config/config.yaml
if [[ -f config/config_hv1.yaml ]]; then
    CONFIG=config/config_hv1.yaml
fi
if [[ $# -eq 2 && "$1" == --config ]]; then
    CONFIG="$2"
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--config PATH]" >&2
    exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
    echo "Config does not exist: $CONFIG" >&2
    exit 1
fi

if [[ -n "${HV_PYTHON:-}" ]]; then
    RUN_PYTHON="$HV_PYTHON"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    RUN_PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$HOME/.venv/bin/python" ]]; then
    RUN_PYTHON="$HOME/.venv/bin/python"
else
    RUN_PYTHON=python3
fi

if "$TMUX_PATH" has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists." >&2
    exit 1
fi

# Quote individual arguments for the shell used by tmux, including paths with spaces.
printf -v controller_command '%q ' "$RUN_PYTHON" main.py --config "$CONFIG"
printf -v sync_command '%q ' env "HV_PYTHON=$RUN_PYTHON" ./sync_db.sh --config "$CONFIG"
controller_pane="$("$TMUX_PATH" new-session -d -P -F '#{pane_id}' \
    -s "$SESSION_NAME" -c "$SCRIPT_DIR" "while true; do $controller_command; sleep 1; done")"
if ! "$TMUX_PATH" split-window -h -t "$controller_pane" -c "$SCRIPT_DIR" \
        "while true; do $sync_command; sleep 5; done"; then
    "$TMUX_PATH" kill-session -t "$SESSION_NAME"
    exit 1
fi
"$TMUX_PATH" select-pane -t "$controller_pane"
echo "Started '$SESSION_NAME': controller on the left, database sync on the right."
