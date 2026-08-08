from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_source_environment as verifier


def test_probe_qt_runtime_imports_native_gui_modules() -> None:
    modules: dict[str, object] = {
        "PySide6": SimpleNamespace(__version__="6.11.1"),
        "PySide6.QtCore": SimpleNamespace(qVersion=lambda: "6.11.1"),
        "PySide6.QtGui": SimpleNamespace(QImage=object()),
        "PySide6.QtWidgets": SimpleNamespace(QApplication=object()),
    }

    details, error = verifier.probe_qt_runtime(modules.__getitem__)

    assert details == "PySide6 6.11.1, Qt 6.11.1"
    assert error is None


def test_probe_qt_runtime_reports_windows_dll_import_failure() -> None:
    def import_with_broken_widgets(name: str) -> object:
        if name == "PySide6.QtWidgets":
            raise ImportError(
                "DLL load failed while importing QtWidgets: "
                "The specified procedure could not be found"
            )
        return SimpleNamespace(
            __version__="6.11.1",
            qVersion=lambda: "6.11.1",
            QImage=object(),
        )

    details, error = verifier.probe_qt_runtime(import_with_broken_widgets)

    assert details is None
    assert error is not None
    assert "DLL load failed while importing QtWidgets" in error


def test_main_uses_distinct_exit_code_for_qt_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        verifier,
        "probe_qt_runtime",
        lambda: (None, "ImportError: DLL load failed while importing QtWidgets"),
    )

    assert verifier.main() == 3
    captured = capsys.readouterr()
    assert "PySide6/Qt runtime" in captured.err


def test_conda_backed_standard_venv_is_rejected() -> None:
    assert verifier.is_conda_backed_venv(
        prefix=r"C:\work\project\.venv",
        base_prefix=r"C:\tools\miniconda3",
    )


def test_direct_conda_environment_is_not_misclassified_as_mixed_venv() -> None:
    assert not verifier.is_conda_backed_venv(
        prefix=r"C:\tools\miniconda3\envs\lidar-label-tool",
        base_prefix=r"C:\tools\miniconda3\envs\lidar-label-tool",
    )


def test_windows_setup_and_launchers_keep_qt_repair_contract() -> None:
    project_root = Path(__file__).resolve().parents[2]
    setup = (project_root / "scripts" / "setup_windows.ps1").read_text(
        encoding="utf-8"
    )
    run_gui = (
        project_root / "launchers" / "windows" / "run_windows.bat"
    ).read_text(encoding="utf-8")
    run_calibration = (
        project_root / "launchers" / "windows" / "run_calibration.bat"
    ).read_text(encoding="utf-8")

    assert "[switch]$Repair" in setup
    assert "[switch]$Recreate" in setup
    assert "--force-reinstall" in setup
    assert "Repair-LockedQtRuntime" in setup
    assert "Remove-ProjectEnvironment" in setup
    assert "Test-CondaBasePython" in setup
    assert "Ignoring active Conda environment" in setup
    assert "verify_source_environment.py" in run_gui
    assert "setup_windows.bat -Repair" in run_gui
    assert 'set "CONDA_PREFIX="' in run_gui
    assert "verify_source_environment.py" in run_calibration
    assert "setup_windows.bat -Recreate" in run_calibration
