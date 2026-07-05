from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from lidar_label_tool.services.dataset_preflight import inspect_dataset
from lidar_label_tool.ui.main_window import MainWindow


def _show_open_error(candidate: Path, exc: Exception) -> None:
    QMessageBox.critical(
        None,
        "데이터셋을 열 수 없음",
        "선택한 폴더는 현재 지원되는 데이터셋이 아닙니다.\n\n"
        f"폴더: {candidate}\n"
        f"원인: {type(exc).__name__}: {exc}\n\n"
        "압축 파일이 아니라 dataset.json 또는 schema.json + segment.json이 있는 "
        "데이터셋 폴더를 선택하세요.",
    )


def _choose_workspace(dataset_root: Path, write_error: str | None) -> Path | None:
    QMessageBox.warning(
        None,
        "데이터셋 폴더에 저장할 수 없음",
        "포인트와 이미지는 열 수 있지만 작업 라벨을 데이터셋 옆에 저장할 수 없습니다.\n\n"
        f"데이터셋: {dataset_root}\n"
        f"원인: {write_error or '쓰기 권한 없음'}\n\n"
        "다음 창에서 쓰기 가능한 별도 작업 폴더를 선택하세요. "
        "원본 데이터셋은 변경하지 않습니다.",
    )
    selected = QFileDialog.getExistingDirectory(
        None,
        "별도 라벨 작업 폴더 선택",
        str(Path.home()),
    )
    return Path(selected) if selected else None


def run_gui(dataset_root: Path | None, config_path: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LiDAR Label Tool")
    interactive_selection = dataset_root is None
    selected_root = dataset_root

    while True:
        if selected_root is None:
            selected = QFileDialog.getExistingDirectory(
                None,
                "LiDAR 데이터셋 폴더 선택",
                str(Path.cwd()),
            )
            if not selected:
                return 0
            selected_root = Path(selected)

        workspace_root: Path | None = None
        try:
            preflight = inspect_dataset(selected_root)
        except (OSError, ValueError, KeyError) as exc:
            _show_open_error(selected_root, exc)
            if not interactive_selection:
                return 2
            selected_root = None
            continue

        while not preflight.working_directory_writable:
            workspace_root = _choose_workspace(selected_root, preflight.write_error)
            if workspace_root is None:
                if not interactive_selection:
                    return 0
                selected_root = None
                break
            preflight = inspect_dataset(selected_root, workspace_root=workspace_root)
        if selected_root is None:
            continue

        if interactive_selection:
            answer = QMessageBox.question(
                None,
                "데이터셋 확인",
                preflight.summary_text() + "\n\n이 데이터셋을 여시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                selected_root = None
                continue

        try:
            window = MainWindow(selected_root, config_path, workspace_root)
        except (OSError, ValueError, KeyError) as exc:
            _show_open_error(selected_root, exc)
            if not interactive_selection:
                return 2
            selected_root = None
            continue
        window.show()
        return app.exec()
