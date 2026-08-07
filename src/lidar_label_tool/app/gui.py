from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from lidar_label_tool.app.config import load_config
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.dataset_preflight import (
    DatasetPreflight,
    PreflightReport,
    inspect_dataset,
    validate_dataset,
)
from lidar_label_tool.services.session_lock import (
    SessionLock,
    SessionLockExistsError,
    SessionLockInfo,
)
from lidar_label_tool.services.session_lock_v2 import (
    V2SessionLock,
    V2SessionLockExistsError,
    V2SessionLockInfo,
)
from lidar_label_tool.ui.main_window import MainWindow
from lidar_label_tool.ui.dataset_setup_dialog import DatasetSetupDialog
from lidar_label_tool.ui.workflow_dialog import WorkflowDialog


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


def _acquire_session_lock(
    dataset_root: Path,
    workspace_root: Path | None,
    profile_id: str | None = None,
) -> SessionLock | V2SessionLock | None:
    adapter = open_dataset_adapter(dataset_root, profile_id=profile_id)
    index = adapter.scan()
    repository = open_label_repository(adapter, workspace_root=workspace_root)
    lock: Any = (
        V2SessionLock(repository)
        if isinstance(repository, V2LabelRepository)
        else SessionLock(repository.annotation_dir)
    )
    inspection = lock.inspect()
    force = inspection.status in {"stale", "malformed"}
    if inspection.status == "active":
        existing_info = inspection.info
        details = (
            f"호스트: {existing_info.hostname}\nPID: {existing_info.pid}\n"
            f"사용자: {existing_info.username or '알 수 없음'}\n"
            f"시작: {existing_info.started_at_utc}"
            if existing_info is not None
            else "세션 정보 없음"
        )
        answer = QMessageBox.question(
            None,
            "이미 열린 데이터셋",
            "이 데이터셋을 편집 중인 세션이 있습니다. 동시에 편집하면 저장 충돌이 "
            f"발생할 수 있습니다.\n\n{details}\n\n그래도 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        force = True
    elif inspection.status == "malformed":
        QMessageBox.warning(
            None,
            "손상된 세션 잠금 교체",
            "기존 세션 잠금 파일을 읽을 수 없어 새 잠금으로 교체합니다.\n\n"
            f"{inspection.error or '형식 오류'}",
        )
    info: Any = (
        V2SessionLockInfo.current(repository)
        if isinstance(repository, V2LabelRepository)
        else SessionLockInfo.current(
            dataset_id=index.dataset_id,
            dataset_root=dataset_root,
            workspace_root=workspace_root,
        )
    )
    try:
        lock.acquire(info, force=force)
    except (SessionLockExistsError, V2SessionLockExistsError) as exc:
        raced = exc.inspection.info
        raced_details = (
            f"호스트: {raced.hostname}\nPID: {raced.pid}\n시작: {raced.started_at_utc}"
            if raced is not None
            else exc.inspection.status
        )
        answer = QMessageBox.question(
            None,
            "동시에 생성된 세션 잠금",
            "데이터셋을 여는 동안 다른 세션이 잠금을 생성했습니다.\n\n"
            f"{raced_details}\n\n그래도 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        lock.acquire(info, force=True)
    return lock


def _choose_v2_profile(dataset_root: Path) -> tuple[bool, str | None]:
    adapter = open_dataset_adapter(dataset_root)
    if not isinstance(adapter, DeviceCentricV2Adapter):
        return True, None
    manifest = adapter.manifest
    if len(manifest.profiles) == 1:
        return True, manifest.profiles[0].id
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
        "LiDAR 프로필 선택",
        "이번 작업에서 사용할 LiDAR를 선택하세요. 여러 LiDAR를 합치지 않습니다.",
        labels,
        default_index,
        False,
    )
    if not accepted:
        return False, None
    return True, manifest.profiles[labels.index(selected)].id


def _confirm_dataset_open(
    preflight: DatasetPreflight,
    report: PreflightReport,
    *,
    always_confirm: bool,
) -> bool:
    summary = preflight.summary_text() + "\n\nQA 사전 검사:\n" + report.short_summary_ko()
    if report.error_count and report.usable_frame_count == 0:
        QMessageBox.critical(
            None,
            "라벨링 가능한 LiDAR 프레임 없음",
            summary
            + "\n\n오류를 수정한 뒤 다시 여세요. 자세한 내용은 CLI preflight로 확인할 수 있습니다.",
        )
        return False
    if report.error_count:
        answer = QMessageBox.question(
            None,
            "데이터셋 QA 오류 발견",
            summary
            + "\n\n일부 데이터는 사용할 수 있지만 오류가 있습니다. 그래도 여시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes
    if not always_confirm:
        return True
    answer = QMessageBox.question(
        None,
        "데이터셋 확인",
        summary + "\n\n이 데이터셋을 여시겠습니까?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def run_gui(
    dataset_root: Path | None,
    config_path: Path,
    *,
    profile_id: str | None = None,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LiDAR Label Tool")
    interactive_selection = dataset_root is None
    selected_root = dataset_root
    selected_profile_id: str | None = profile_id
    config = load_config(config_path)

    while True:
        if selected_root is None:
            workflow = WorkflowDialog(config_path)
            if workflow.exec() != QDialog.DialogCode.Accepted:
                return 0
            selected_root = workflow.selected_dataset
            selected_profile_id = None
            if selected_root is None:
                return 0

        assert selected_root is not None
        if (
            not (selected_root / "dataset.json").exists()
            and not WaymoFrameCentricAdapter.can_open(selected_root)
        ):
            setup_dialog = DatasetSetupDialog(selected_root, config)
            if setup_dialog.exec() != QDialog.DialogCode.Accepted:
                if not interactive_selection:
                    return 0
                selected_root = None
                selected_profile_id = None
                continue
            selected_root = setup_dialog.selected_config_root
            selected_profile_id = setup_dialog.selected_profile_id
            if selected_root is None:
                if not interactive_selection:
                    return 2
                continue

        opening_candidate = selected_root
        workspace_root: Path | None = None
        try:
            profile_accepted = True
            if selected_profile_id is None:
                profile_accepted, selected_profile_id = _choose_v2_profile(opening_candidate)
            if not profile_accepted:
                if not interactive_selection:
                    return 0
                selected_root = None
                continue
            preflight = inspect_dataset(
                opening_candidate,
                profile_id=selected_profile_id,
            )
        except (OSError, ValueError, KeyError) as exc:
            _show_open_error(opening_candidate, exc)
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
            preflight = inspect_dataset(
                selected_root,
                workspace_root=workspace_root,
                profile_id=selected_profile_id,
            )
        if selected_root is None:
            continue

        report = validate_dataset(
            selected_root,
            class_mapping=config["source_class_mappings"],
            workspace_root=workspace_root,
            verify_images=False,
            profile_id=selected_profile_id,
        )
        if not _confirm_dataset_open(
            preflight, report, always_confirm=interactive_selection
        ):
            if interactive_selection:
                selected_root = None
                continue
            return 2 if report.error_count else 0

        session_lock: SessionLock | V2SessionLock | None = None
        assert selected_root is not None
        opening_root = selected_root
        try:
            session_lock = _acquire_session_lock(
                opening_root,
                workspace_root,
                selected_profile_id,
            )
            if session_lock is None:
                if not interactive_selection:
                    return 0
                selected_root = None
                continue
            window = MainWindow(
                opening_root,
                config_path,
                workspace_root,
                session_lock=session_lock,
                profile_id=selected_profile_id,
            )
        except (OSError, ValueError, KeyError) as exc:
            if session_lock is not None:
                try:
                    session_lock.release()
                except OSError:
                    pass
            _show_open_error(opening_root, exc)
            if not interactive_selection:
                return 2
            selected_root = None
            continue
        window.show()
        return app.exec()
