#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_root/.venv/bin/python"

if [[ ! -x "$venv_python" ]]; then
    echo "[ERROR] The project virtual environment was not found." >&2
    echo "Run ./setup_linux.sh first." >&2
    exit 1
fi

cd "$project_root"
exec "$venv_python" -m lidar_label_tool gui "$@"
