from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from lidar_label_tool.app.config import load_config
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
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


def _acquire_session_lock(
    dataset_root: Path, workspace_root: Path | None
) -> SessionLock | None:
    index = open_dataset_adapter(dataset_root).scan()
    repository = (
        LabelRepository.for_workspace(workspace_root, index.dataset_id)
        if workspace_root is not None
        else LabelRepository.for_sidecar(dataset_root, index.dataset_id)
    )
    lock = SessionLock(repository.annotation_dir)
    inspection = lock.inspect()
    force = inspection.status in {"stale", "malformed"}
    if inspection.status == "active":
        info = inspection.info
        details = (
            f"호스트: {info.hostname}\nPID: {info.pid}\n"
            f"사용자: {info.username or '알 수 없음'}\n시작: {info.started_at_utc}"
            if info is not None
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
    info = SessionLockInfo.current(
        dataset_id=index.dataset_id,
        dataset_root=dataset_root,
        workspace_root=workspace_root,
    )
    try:
        lock.acquire(info, force=force)
    except SessionLockExistsError as exc:
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


def run_gui(dataset_root: Path | None, config_path: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LiDAR Label Tool")
    interactive_selection = dataset_root is None
    selected_root = dataset_root
    config = load_config(config_path)

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

        report = validate_dataset(
            selected_root,
            class_mapping=config["source_class_mappings"],
            workspace_root=workspace_root,
            verify_images=False,
        )
        if not _confirm_dataset_open(
            preflight, report, always_confirm=interactive_selection
        ):
            if interactive_selection:
                selected_root = None
                continue
            return 2 if report.error_count else 0

        session_lock: SessionLock | None = None
        assert selected_root is not None
        opening_root = selected_root
        try:
            session_lock = _acquire_session_lock(opening_root, workspace_root)
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
