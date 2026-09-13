from __future__ import annotations

from collections.abc import Callable
import traceback
from typing import TypeVar, cast

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget

from lidar_label_tool.services.background_task import TaskCancelled, TaskControl, TaskProgress


Result = TypeVar("Result")


class CallableWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    progress = Signal(object)
    finished = Signal()

    def __init__(self, task: Callable[[TaskControl], object]) -> None:
        super().__init__()
        self.task = task
        self.control = TaskControl(self.progress.emit)

    @Slot()
    def run(self) -> None:
        try:
            self.control.check_cancelled()
            # A service may have just committed successfully. Do not turn a
            # late cancel click into a misleading cancellation after that point.
            self.succeeded.emit(self.task(self.control))
        except TaskCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())
        finally:
            self.finished.emit()


class BusyTaskDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, title: str, task: Callable[[TaskControl], object]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.result_value: object | None = None
        self.error_summary: str | None = None
        self.error_details: str | None = None
        self.cancel_summary: str | None = None
        self._finished = False
        layout = QVBoxLayout(self)
        self.status = QLabel("작업 준비 중")
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.request_cancel)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        self._task_thread = QThread(self)
        self.worker = CallableWorker(task)
        self.worker.moveToThread(self._task_thread)
        self._task_thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self._succeeded)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._task_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self._task_thread.finished.connect(self._thread_finished)
        QTimer.singleShot(0, self._task_thread.start)

    @Slot(object)
    def _progress(self, update: TaskProgress) -> None:
        if self.worker.control.cancelled:
            return
        self.status.setText(update.message)
        if update.total > 0:
            self.progress.setRange(0, update.total)
            self.progress.setValue(min(update.completed, update.total))
        else:
            self.progress.setRange(0, 0)

    @Slot(object)
    def _succeeded(self, result: object) -> None:
        self.result_value = result
        self.status.setText("완료")

    @Slot(str, str)
    def _failed(self, summary: str, details: str) -> None:
        self.error_summary, self.error_details = summary, details

    @Slot(str)
    def _cancelled(self, summary: str) -> None:
        self.cancel_summary = summary

    @Slot()
    def _thread_finished(self) -> None:
        self._finished = True
        if self.error_summary is not None or self.cancel_summary is not None:
            QDialog.reject(self)
        else:
            QDialog.accept(self)

    @Slot()
    def request_cancel(self) -> None:
        if self._finished:
            return
        self.worker.control.cancel()
        self.cancel_button.setEnabled(False)
        self.status.setText("취소 요청 중 — 현재 파일의 안전한 처리 경계에서 중단합니다.")

    def reject(self) -> None:
        if not self._finished:
            self.request_cancel()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._finished:
            self.request_cancel()
            event.ignore()
            return
        super().closeEvent(event)


def run_task(
    parent: QWidget | None, title: str, task: Callable[[TaskControl], Result]
) -> Result | None:
    dialog = BusyTaskDialog(parent, title, task)
    dialog.exec()
    if dialog.error_summary:
        message = QMessageBox(QMessageBox.Icon.Critical, title, dialog.error_summary, parent=parent)
        message.setDetailedText(dialog.error_details or "")
        message.exec()
        return None
    if dialog.cancel_summary is not None:
        QMessageBox.information(parent, title, dialog.cancel_summary)
        return None
    return cast(Result, dialog.result_value)
