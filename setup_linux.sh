#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_command="${PYTHON_BIN:-python3}"
venv_python="$project_root/.venv/bin/python"

cd "$project_root"

if ! command -v "$python_command" >/dev/null 2>&1; then
    echo "[ERROR] $python_command was not found." >&2
    echo "Install Python 3.10 or newer, or set PYTHON_BIN." >&2
    exit 1
fi

"$python_command" -c \
    'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
    echo "[ERROR] Python 3.10 or newer is required." >&2
    exit 1
}

if [[ ! -x "$venv_python" ]]; then
    "$python_command" -m venv "$project_root/.venv"
fi

"$venv_python" -m pip install --requirement requirements-bootstrap-lock.txt
"$venv_python" -m pip install --requirement requirements-lock.txt
"$venv_python" -m pip install --no-build-isolation --no-deps --editable .
"$venv_python" scripts/verify_source_environment.py

echo
echo "Setup completed. Run ./run_linux.sh to start LiDAR Label Tool."
