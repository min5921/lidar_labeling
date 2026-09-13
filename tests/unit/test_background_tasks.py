from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from lidar_label_tool.services.background_task import TaskCancelled, TaskControl, TaskProgress
from lidar_label_tool.services.dataset_preflight import validate_dataset
from lidar_label_tool.services.dataset_v2_validation import validate_dataset_v2
from lidar_label_tool.services.label_statistics import collect_label_statistics
from tests.fixture_builders import CLASS_MAPPING, create_device_dataset, create_v2_dataset


@pytest.fixture
def application(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_task_control_progress_and_pre_cancel() -> None:
    updates: list[TaskProgress] = []
    task = TaskControl(updates.append)
    task.report("scan", 1, 3, "첫 파일")
    assert updates == [TaskProgress("scan", 1, 3, "첫 파일")]
    task.cancel()
    assert task.cancelled
    with pytest.raises(TaskCancelled):
        task.report("scan", 2, 3, "취소 뒤에는 보내지 않음")
    assert len(updates) == 1


@pytest.mark.parametrize("operation", ["preflight", "statistics", "v2"])
def test_read_only_services_cancel_mid_scan_without_writes(tmp_path: Path, operation: str) -> None:
    if operation == "v2":
        create_v2_dataset(tmp_path, frame_count=3)
    else:
        create_device_dataset(tmp_path, frame_count=3)
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    updates: list[TaskProgress] = []
    def progress(update: TaskProgress) -> None:
        updates.append(update)
        if update.total > 0:
            task.cancel()
    task = TaskControl(progress)
    with pytest.raises(TaskCancelled):
        if operation == "preflight":
            validate_dataset(tmp_path, class_mapping=CLASS_MAPPING, task=task)
        elif operation == "statistics":
            collect_label_statistics(tmp_path, class_mapping=CLASS_MAPPING, task=task)
        else:
            validate_dataset_v2(tmp_path, task=task)
    assert any(update.total == 3 for update in updates)
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("operation", ["preflight", "statistics", "v2"])
def test_read_only_last_frame_cancel_is_not_reported_as_success(tmp_path: Path, operation: str) -> None:
    if operation == "v2":
        create_v2_dataset(tmp_path, frame_count=1)
    else:
        create_device_dataset(tmp_path, frame_count=1)
    task = TaskControl(lambda update: task.cancel() if update.total == 1 else None)
    with pytest.raises(TaskCancelled):
        if operation == "preflight":
            validate_dataset(tmp_path, task=task)
        elif operation == "statistics":
            collect_label_statistics(tmp_path, class_mapping=CLASS_MAPPING, task=task)
        else:
            validate_dataset_v2(tmp_path, task=task)


def test_v2_pre_cancel_is_checked_before_manifest_io(tmp_path: Path) -> None:
    task = TaskControl()
    task.cancel()
    with patch("lidar_label_tool.services.dataset_v2_validation.load_dataset_manifest_v2") as load:
        with pytest.raises(TaskCancelled):
            validate_dataset_v2(tmp_path, task=task)
        load.assert_not_called()


def test_callable_worker_pre_cancel_and_post_commit_cancel(application: object) -> None:
    from lidar_label_tool.ui.task_dialog import CallableWorker

    calls: list[str] = []
    worker = CallableWorker(lambda task: calls.append("should not run"))
    cancelled: list[str] = []
    finished: list[bool] = []
    worker.cancelled.connect(cancelled.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.control.cancel()
    worker.run()
    assert not calls and cancelled and finished == [True]

    def committed(task: TaskControl) -> str:
        calls.append("committed")
        task.cancel()
        return "safe result"
    worker = CallableWorker(committed)
    results: list[object] = []
    worker.succeeded.connect(results.append)
    worker.run()
    assert calls == ["committed"]
    assert results == ["safe result"]


def test_busy_dialog_close_cooperatively_cancels_without_destroying_running_thread(application: object) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog

    from lidar_label_tool.ui.task_dialog import BusyTaskDialog

    started = Event()
    release = Event()
    def work(task: TaskControl) -> str:
        task.report("scan", 1, 4, "검사 진행 중")
        started.set()
        while not release.wait(0.005):
            task.check_cancelled()
        return "complete"
    dialog = BusyTaskDialog(None, "취소 테스트", work)
    observed: list[tuple[bool, bool]] = []
    poll = QTimer(dialog)
    def request_close() -> None:
        if not started.is_set():
            return
        poll.stop()
        running = dialog._task_thread.isRunning()
        accepted = dialog.close()
        observed.append((running, accepted))
    poll.timeout.connect(request_close)
    poll.start(1)
    timeout = QTimer(dialog)
    timeout.setSingleShot(True)
    timeout.timeout.connect(release.set)
    timeout.start(5000)
    try:
        assert dialog.exec() == QDialog.DialogCode.Rejected
        assert observed == [(True, False)]
        assert not dialog._task_thread.isRunning()
        assert dialog.cancel_summary
        assert dialog.result_value is None
    finally:
        release.set()
        dialog._task_thread.wait(1000)
