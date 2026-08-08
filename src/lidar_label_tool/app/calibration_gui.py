from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.ui.calibration_editor import CalibrationEditorWindow


def _choose_profile(dataset_root: Path, profile_id: str | None) -> str | None:
    if profile_id is not None:
        return profile_id
    adapter = open_dataset_adapter(dataset_root)
    if not isinstance(adapter, DeviceCentricV2Adapter):
        return None
    manifest = adapter.manifest
    if len(manifest.profiles) == 1:
        return manifest.profiles[0].id
    labels = [f"{profile.display_name} ({profile.id})" for profile in manifest.profiles]
    default_index = next(
        (
            index
            for index, profile in enumerate(manifest.profiles)
            if profile.id == manifest.default_profile_id
        ),
        0,
    )
    selected, accepted = QInputDialog.getItem(
        None,
        "Calibration 대상 LiDAR 프로필",
        "카메라와 보정할 label-ready LiDAR 프로필을 선택하세요.",
        labels,
        default_index,
        False,
    )
    if not accepted:
        raise RuntimeError("profile selection was cancelled")
    return manifest.profiles[labels.index(selected)].id


def run_calibration_gui(
    dataset_root: Path | None,
    config_path: Path,
    *,
    profile_id: str | None = None,
    calibration_path: Path | None = None,
    output_path: Path | None = None,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LiDAR Camera Calibration Editor")
    selected_root = Path(dataset_root) if dataset_root is not None else None
    if selected_root is None:
        selected = QFileDialog.getExistingDirectory(
            None,
            "Calibration할 LiDAR·카메라 데이터셋 선택",
            str(Path.home()),
        )
        if not selected:
            return 0
        selected_root = Path(selected)
    try:
        selected_profile = _choose_profile(selected_root, profile_id)
        window = CalibrationEditorWindow(
            selected_root,
            config_path,
            profile_id=selected_profile,
            calibration_path=calibration_path,
            output_path=output_path,
        )
    except RuntimeError as exc:
        if str(exc) == "profile selection was cancelled":
            return 0
        QMessageBox.critical(None, "Calibration 도구를 열 수 없음", str(exc))
        return 2
    except (OSError, KeyError, TypeError, ValueError) as exc:
        QMessageBox.critical(
            None,
            "Calibration 도구를 열 수 없음",
            f"{type(exc).__name__}: {exc}",
        )
        return 2
    window.show()
    return app.exec()
