#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_command="python3"
venv_directory=".build/linux-portable-venv"
one_file=0
skip_tests=0
skip_dependency_install=0
skip_smoke=0

usage() {
    cat <<'EOF'
Usage: packaging/build_linux_portable.sh [options]

Options:
  --python COMMAND          Python 3.10+ command (default: python3)
  --venv DIRECTORY         Build venv relative to repo root
  --onefile                Build a single ELF executable
  --skip-tests             Skip pytest and ruff
  --skip-dependency-install
                           Reuse an existing populated build venv
  --skip-smoke             Skip packaged launcher smoke test
  -h, --help               Show this help
EOF
}

while (($#)); do
    case "$1" in
        --python)
            python_command="${2:?--python requires a value}"
            shift 2
            ;;
        --venv)
            venv_directory="${2:?--venv requires a value}"
            shift 2
            ;;
        --onefile)
            one_file=1
            shift
            ;;
        --skip-tests)
            skip_tests=1
            shift
            ;;
        --skip-dependency-install)
            skip_dependency_install=1
            shift
            ;;
        --skip-smoke)
            skip_smoke=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Linux builds must run on Linux; PyInstaller is not a cross-compiler." >&2
    exit 2
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "This release script currently targets Linux x86_64 only." >&2
    exit 2
fi

if [[ "$venv_directory" = /* ]]; then
    venv_path="$venv_directory"
else
    venv_path="$project_root/$venv_directory"
fi
venv_python="$venv_path/bin/python"
constraints="$project_root/packaging/linux_build_constraints.txt"

cd "$project_root"

if [[ ! -x "$venv_python" ]]; then
    if ((skip_dependency_install)); then
        echo "Build venv does not exist: $venv_path" >&2
        exit 2
    fi
    "$python_command" -m venv "$venv_path"
fi

"$venv_python" -c \
    "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'Python 3.10 or newer is required')"

if ((skip_dependency_install)); then
    "$venv_python" -c "import OpenGL, PyInstaller, PySide6, pyqtgraph"
else
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install \
        --constraint "$constraints" \
        ".[gui,validation,dev,portable]"
fi

if ((!skip_tests)); then
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software "$venv_python" -m pytest
    "$venv_python" -m ruff check .
fi

pyinstaller_arguments=(
    --noconfirm
    --clean
    --name LiDARLabelTool
    --distpath "$project_root/dist"
    --workpath "$project_root/build/pyinstaller-linux"
    --specpath "$project_root/build"
    --collect-all pyqtgraph
    --collect-all OpenGL
    --add-data "$project_root/configs:configs"
    --add-data "$project_root/schemas:schemas"
    --add-data "$project_root/resources:resources"
    --add-data "$project_root/THIRD_PARTY_NOTICES.md:."
)
if ((one_file)); then
    pyinstaller_arguments=(--onefile "${pyinstaller_arguments[@]}")
fi

"$venv_python" -m PyInstaller \
    "${pyinstaller_arguments[@]}" \
    "$project_root/packaging/linux_entry.py"

if ((one_file)); then
    executable="$project_root/dist/LiDARLabelTool"
else
    executable="$project_root/dist/LiDARLabelTool/LiDARLabelTool"
fi
if [[ ! -x "$executable" ]]; then
    echo "Portable executable was not created: $executable" >&2
    exit 1
fi

mkdir -p "$project_root/build"
"$venv_python" -m pip freeze --all \
    >"$project_root/build/linux-build-dependencies.txt"

if ((!skip_smoke)); then
    QT_QPA_PLATFORM=offscreen QT_OPENGL=software \
        timeout 30s "$executable" --smoke-test
fi

echo "Linux portable build complete: $executable"
