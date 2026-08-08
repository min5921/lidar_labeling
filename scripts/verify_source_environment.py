from __future__ import annotations

from collections.abc import Callable
from importlib import import_module, metadata
from pathlib import Path
import re
import sys


LOCK_PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)$")


def locked_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"Unsupported lock entry: {line}")
        requirements[match.group("name")] = match.group("version")
    return requirements


def probe_qt_runtime(
    importer: Callable[[str], object] = import_module,
) -> tuple[str | None, str | None]:
    """Import the native Qt modules needed by both GUI entry points.

    Package metadata alone cannot detect a corrupt wheel install, a copied virtual
    environment, or an incompatible DLL selected by Windows. Importing QtCore,
    QtGui, and QtWidgets exercises the native extension/DLL boundary without
    opening a window.
    """

    try:
        pyside = importer("PySide6")
        qt_core = importer("PySide6.QtCore")
        qt_gui = importer("PySide6.QtGui")
        qt_widgets = importer("PySide6.QtWidgets")

        pyside_version = str(getattr(pyside, "__version__"))
        q_version = getattr(qt_core, "qVersion")
        if not callable(q_version):
            raise TypeError("PySide6.QtCore.qVersion is not callable")
        qt_version = str(q_version())

        # Resolve representative native-backed symbols used by the application.
        getattr(qt_gui, "QImage")
        getattr(qt_widgets, "QApplication")
    except (ImportError, OSError, AttributeError, RuntimeError, TypeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"

    return f"PySide6 {pyside_version}, Qt {qt_version}", None


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 10):
        print(
            f"[ERROR] Python 3.10 or newer is required; found {sys.version.split()[0]}.",
            file=sys.stderr,
        )
        return 2

    expected_packages = locked_requirements(
        project_root / "requirements-bootstrap-lock.txt"
    )
    expected_packages.update(
        locked_requirements(project_root / "requirements-lock.txt")
    )

    mismatches: list[str] = []
    for name, expected in expected_packages.items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{name}: {actual} (expected {expected})")

    try:
        from lidar_label_tool.app.config import default_config_path, load_config

        config_path = default_config_path()
        load_config(config_path)
    except (ImportError, OSError, ValueError) as exc:
        mismatches.append(f"lidar-label-tool/config: {type(exc).__name__}: {exc}")

    qt_runtime, qt_error = probe_qt_runtime()
    if qt_error is not None:
        mismatches.append(f"PySide6/Qt runtime: {qt_error}")

    if mismatches:
        print("[ERROR] Source environment verification failed:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        if qt_error is not None:
            if sys.platform == "win32":
                print(
                    "[ACTION] Run launchers\\windows\\setup_windows.bat -Repair. "
                    "If it still fails, run it with -Recreate.",
                    file=sys.stderr,
                )
                print(
                    "[ACTION] Windows 10 build 1809+ or Windows 11 x64 is "
                    "required for the locked Qt runtime.",
                    file=sys.stderr,
                )
            else:
                print(
                    "[ACTION] Re-run ./launchers/linux/setup_linux.sh and review "
                    "docs/31_LAB_SOURCE_SETUP.md.",
                    file=sys.stderr,
                )
        return 3 if qt_error is not None else 2

    print(
        "[OK] LiDAR Label Tool source environment verified "
        f"(Python {sys.version.split()[0]}, {len(expected_packages)} locked packages; "
        f"{qt_runtime})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
