from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import sys
import traceback
from typing import Any

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool import __version__
from lidar_label_tool.app.config import load_config
from lidar_label_tool.app.runtime_paths import user_settings_path
from lidar_label_tool.services.dataset_preflight import validate_dataset
from lidar_label_tool.services.label_export import export_dataset_labels
from lidar_label_tool.services.label_statistics import collect_label_statistics
from lidar_label_tool.services.one_chip_conversion import (
    CancellationToken,
    ConversionCancelled,
    ConversionProgress,
    OneChipOperationRequest,
    OneChipOperationResult,
    execute_one_chip_operation,
)
from lidar_label_tool.services.one_chip_calibration_verification import (
    verify_calibration,
)


class _ConversionWorker(QObject):
    progress = Signal(object)
    succeeded = Signal(object, object)
    cancelled = Signal()
    failed = Signal(str, str)

    def __init__(self, request: OneChipOperationRequest, token: CancellationToken) -> None:
        super().__init__()
        self.request = request
        self.token = token

    @Slot()
    def run(self) -> None:
        try:
            result = execute_one_chip_operation(
                self.request,
                progress=self.progress.emit,
                cancellation=self.token,
            )
            preflight = None
            if result.mode in {"convert", "resync"}:
                self.token.raise_if_cancelled()
                self.progress.emit(
                    ConversionProgress("preflight", "변환 결과 Preflight 실행 중")
                )
                preflight = validate_dataset(result.output, verify_images=True)
            self.succeeded.emit(result, preflight)
        except ConversionCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())


class _CallableWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self.task())
        except Exception as exc:  # noqa: BLE001 - worker boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())


class _BusyTaskDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, task: Callable[[], object]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.result_value: object | None = None
        self.error_summary: str | None = None
        self.error_details: str | None = None

        layout = QVBoxLayout(self)
        self.status = QLabel("작업 중")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)

        self.thread = QThread(self)
        self.worker = _CallableWorker(task)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self._succeeded)
        self.worker.failed.connect(self._failed)
        self.worker.succeeded.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        QTimer.singleShot(0, self.thread.start)

    @Slot(object)
    def _succeeded(self, result: object) -> None:
        self.result_value = result
        self.status.setText("완료")

    @Slot(str, str)
    def _failed(self, summary: str, details: str) -> None:
        self.error_summary = summary
        self.error_details = details
        self.status.setText("실패")

    @Slot()
    def _thread_finished(self) -> None:
        if self.error_summary is None:
            QDialog.accept(self)
        else:
            QDialog.reject(self)

    def reject(self) -> None:
        if self.thread.isRunning():
            return
        super().reject()


def _run_task(
    parent: QWidget, title: str, task: Callable[[], object]
) -> object | None:
    dialog = _BusyTaskDialog(parent, title, task)
    dialog.exec()
    if dialog.error_summary:
        message = QMessageBox(QMessageBox.Icon.Critical, title, dialog.error_summary, parent=parent)
        message.setDetailedText(dialog.error_details or "")
        message.exec()
        return None
    return dialog.result_value


class _PathRow(QWidget):
    def __init__(self, browse: Callable[[], None], *, placeholder: str = "") -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.button = QPushButton()
        self.button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.button.setToolTip("경로 선택")
        self.button.setFixedWidth(34)
        self.button.clicked.connect(browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)


class OneChipConversionDialog(QDialog):
    MODE_TITLES = {
        "convert": "원본 데이터 변환",
        "resync": "기존 데이터 재동기화",
        "calibration": "Calibration JSON 생성",
    }

    def __init__(self, parent: QWidget, mode: str) -> None:
        super().__init__(parent)
        self.mode = mode
        self.selected_dataset: Path | None = None
        self.operation_result: OneChipOperationResult | None = None
        self._thread: QThread | None = None
        self._worker: _ConversionWorker | None = None
        self._token: CancellationToken | None = None
        settings_path = user_settings_path()
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(settings_path), QSettings.Format.IniFormat)

        self.setWindowTitle(self.MODE_TITLES[mode])
        self.resize(760, 610)
        layout = QVBoxLayout(self)

        paths = QGroupBox("경로")
        path_form = QFormLayout(paths)
        self.source_row = _PathRow(self._browse_source, placeholder="원본 calibration/rosbags 루트")
        self.calibration_row = _PathRow(
            self._browse_calibration, placeholder="Calibration YAML 폴더"
        )
        self.output_row = _PathRow(self._browse_output, placeholder="출력 경로")
        path_form.addRow("원본", self.source_row)
        path_form.addRow("Calibration", self.calibration_row)
        path_form.addRow("출력", self.output_row)
        layout.addWidget(paths)

        options = QGroupBox("변환 설정")
        option_form = QFormLayout(options)
        self.dataset_id = QLineEdit("one_chip")
        self.bags = QLineEdit()
        self.bags.setPlaceholderText("비우면 rosbags 아래 모든 bag")
        self.timestamp_source = QComboBox()
        self.timestamp_source.addItems(["header_aligned", "header", "log", "publish"])
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0.0, 10000.0)
        self.tolerance.setDecimals(3)
        self.tolerance.setSuffix(" ms")
        self.tolerance.setValue(70.0)
        self.layout_mode = QComboBox()
        self.layout_mode.addItems(["simple", "legacy"])
        self.camera_frame = QComboBox()
        self.camera_frame.addItems(["tool_camera", "as_provided"])
        self.image_mode = QComboBox()
        self.image_mode.addItems(["block_demosaic", "grayscale"])
        option_form.addRow("Dataset ID", self.dataset_id)
        option_form.addRow("Bag", self.bags)
        option_form.addRow("Timestamp", self.timestamp_source)
        option_form.addRow("Sync tolerance", self.tolerance)
        option_form.addRow("폴더 구조", self.layout_mode)
        option_form.addRow("Camera frame", self.camera_frame)
        option_form.addRow("이미지 변환", self.image_mode)
        layout.addWidget(options)
        if mode == "calibration":
            self.source_row.setVisible(False)
            path_form.labelForField(self.source_row).setVisible(False)
            options.setVisible(False)
        elif mode == "resync":
            self.calibration_row.setVisible(False)
            path_form.labelForField(self.calibration_row).setVisible(False)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status = QLabel("대기")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

        buttons = QDialogButtonBox()
        self.start_button = buttons.addButton("실행", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = buttons.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        self.open_button = buttons.addButton(
            "완료 데이터셋 열기", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.open_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel_or_close)
        self.open_button.clicked.connect(self._open_result)
        layout.addWidget(buttons)
        self._restore_settings()

    def _restore_settings(self) -> None:
        self.source_row.edit.setText(str(self.settings.value("one_chip/source", "")))
        self.calibration_row.edit.setText(
            str(self.settings.value("one_chip/calibration", ""))
        )
        key = "one_chip/output" if self.mode == "convert" else f"one_chip/{self.mode}_output"
        self.output_row.edit.setText(str(self.settings.value(key, "")))
        self.dataset_id.setText(str(self.settings.value("one_chip/dataset_id", "one_chip")))
        self.timestamp_source.setCurrentText(
            str(self.settings.value("one_chip/timestamp_source", "header_aligned"))
        )
        self.tolerance.setValue(float(self.settings.value("one_chip/tolerance_ms", 70.0)))

    def _save_settings(self) -> None:
        self.settings.setValue("one_chip/source", self.source_row.edit.text().strip())
        self.settings.setValue(
            "one_chip/calibration", self.calibration_row.edit.text().strip()
        )
        key = "one_chip/output" if self.mode == "convert" else f"one_chip/{self.mode}_output"
        self.settings.setValue(key, self.output_row.edit.text().strip())
        self.settings.setValue("one_chip/dataset_id", self.dataset_id.text().strip())
        self.settings.setValue("one_chip/timestamp_source", self.timestamp_source.currentText())
        self.settings.setValue("one_chip/tolerance_ms", self.tolerance.value())
        self.settings.sync()

    def _browse_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "원본 데이터 루트 선택")
        if not selected:
            return
        root = Path(selected)
        self.source_row.edit.setText(str(root))
        if not self.calibration_row.edit.text().strip():
            results = root / "calibration" / "results"
            candidates = sorted(path for path in results.glob("*") if path.is_dir())
            if len(candidates) == 1:
                self.calibration_row.edit.setText(str(candidates[0]))

    def _browse_calibration(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Calibration YAML 폴더 선택")
        if selected:
            self.calibration_row.edit.setText(selected)

    def _browse_output(self) -> None:
        if self.mode == "calibration":
            selected, _ = QFileDialog.getSaveFileName(
                self, "Calibration JSON 출력", "calibration.json", "JSON (*.json)"
            )
            if selected:
                self.output_row.edit.setText(selected)
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            "기존 데이터셋 선택" if self.mode == "resync" else "출력 상위 폴더 선택",
        )
        if not selected:
            return
        target = Path(selected)
        if self.mode == "convert":
            source_name = Path(self.source_row.edit.text().strip()).name or "one_chip"
            target = target / f"{source_name}_converted"
        self.output_row.edit.setText(str(target))

    def _request(self) -> OneChipOperationRequest:
        source_text = self.source_row.edit.text().strip()
        calibration_text = self.calibration_row.edit.text().strip()
        output_text = self.output_row.edit.text().strip()
        if self.mode != "calibration" and not source_text:
            raise ValueError("원본 데이터 루트를 선택하세요.")
        if self.mode in {"convert", "calibration"} and not calibration_text:
            raise ValueError("Calibration YAML 폴더를 선택하세요.")
        if not output_text:
            raise ValueError("출력 경로를 선택하세요.")
        source = Path(source_text or calibration_text).resolve()
        calibration = Path(calibration_text or source_text).resolve()
        output = Path(output_text).resolve()
        if self.mode != "calibration" and not source.is_dir():
            raise ValueError("원본 데이터 루트가 올바른 폴더가 아닙니다.")
        if self.mode in {"convert", "calibration"} and not calibration.is_dir():
            raise ValueError("Calibration YAML 폴더가 올바르지 않습니다.")
        if self.mode == "convert" and output.exists():
            raise FileExistsError("전체 변환 출력 경로가 이미 존재합니다.")
        if self.mode == "resync" and not (output / "dataset.json").is_file():
            raise FileNotFoundError("재동기화할 dataset.json이 없습니다.")
        bags = tuple(item.strip() for item in self.bags.text().split(",") if item.strip())
        return OneChipOperationRequest(
            mode=self.mode,
            source=source,
            output=output,
            calibration=calibration,
            dataset_id=self.dataset_id.text().strip(),
            bags=bags,
            timestamp_source=self.timestamp_source.currentText(),
            sync_tolerance_ms=self.tolerance.value(),
            dataset_layout=self.layout_mode.currentText(),
            camera_frame_convention=self.camera_frame.currentText(),
            image_mode=self.image_mode.currentText(),
            progress_every=25,
        )

    def _start(self) -> None:
        try:
            request = self._request()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "입력 확인", str(exc))
            return
        self._save_settings()
        self.log.clear()
        self.status.setText("작업 시작")
        self.progress.setRange(0, 0)
        self.start_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self._token = CancellationToken()
        self._thread = QThread(self)
        self._worker = _ConversionWorker(request, self._token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_success)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.failed.connect(self._on_failed)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot(object)
    def _on_progress(self, update: ConversionProgress) -> None:
        self.status.setText(update.message)
        self.log.appendPlainText(f"[{update.stage}] {update.message}")

    @Slot(object, object)
    def _on_success(self, result: OneChipOperationResult, preflight: object) -> None:
        self.operation_result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        summary = f"완료: {result.output}"
        if preflight is not None:
            summary += "\n" + preflight.short_summary_ko()
        self.status.setText(summary)
        self.log.appendPlainText(json.dumps(dict(result.report), ensure_ascii=False, indent=2))
        self.open_button.setEnabled(
            result.mode in {"convert", "resync"} and (result.output / "dataset.json").is_file()
        )
        if preflight is not None and (preflight.error_count or preflight.warning_count):
            details = "\n".join(
                f"[{issue.severity}] {issue.code}: {issue.message}"
                for issue in preflight.issues[:200]
            )
            message = QMessageBox(QMessageBox.Icon.Warning, "변환 결과 QA", summary, parent=self)
            message.setDetailedText(details)
            message.exec()
        else:
            QMessageBox.information(self, "작업 완료", summary)

    @Slot()
    def _on_cancelled(self) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText("작업이 취소되었습니다. 기존 데이터는 보존되었습니다.")
        self.log.appendPlainText("[cancelled] 작업 취소")

    @Slot(str, str)
    def _on_failed(self, summary: str, details: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status.setText(f"실패: {summary}")
        self.log.appendPlainText(details)
        message = QMessageBox(QMessageBox.Icon.Critical, "작업 실패", summary, parent=self)
        message.setDetailedText(details)
        message.exec()

    @Slot()
    def _thread_finished(self) -> None:
        self.start_button.setEnabled(True)
        self._worker = None
        self._thread = None
        self._token = None

    def _cancel_or_close(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            assert self._token is not None
            self._token.cancel()
            self.status.setText("취소 요청 중")
            return
        self.reject()

    def _open_result(self) -> None:
        if self.operation_result is None:
            return
        self.selected_dataset = self.operation_result.output
        self.accept()

    def closeEvent(self, event: Any) -> None:
        if self._thread is not None and self._thread.isRunning():
            assert self._token is not None
            self._token.cancel()
            self.status.setText("취소 요청 중")
            event.ignore()
            return
        super().closeEvent(event)


class LabelExportDialog(QDialog):
    def __init__(self, parent: QWidget, config_path: Path) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.setWindowTitle("라벨 내보내기")
        self.resize(650, 270)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.dataset_row = _PathRow(self._browse_dataset)
        self.workspace_row = _PathRow(self._browse_workspace, placeholder="선택 사항")
        self.output_row = _PathRow(self._browse_output)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["lidar_label_json", "centerpoint_intermediate_json"])
        self.frames = QLineEdit()
        self.frames.setPlaceholderText("비우면 전체, 여러 개는 쉼표로 구분")
        form.addRow("Dataset", self.dataset_row)
        form.addRow("Workspace", self.workspace_row)
        form.addRow("형식", self.format_combo)
        form.addRow("Frame ID", self.frames)
        form.addRow("출력", self.output_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_dataset(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Dataset 선택")
        if selected:
            self.dataset_row.edit.setText(selected)

    def _browse_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Workspace 선택")
        if selected:
            self.workspace_row.edit.setText(selected)

    def _browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Export 출력 폴더 선택")
        if selected:
            self.output_row.edit.setText(selected)

    def _export(self) -> None:
        dataset = Path(self.dataset_row.edit.text().strip())
        output = Path(self.output_row.edit.text().strip())
        if not (dataset / "dataset.json").is_file() and not (dataset / "schema.json").is_file():
            QMessageBox.warning(self, "입력 확인", "지원되는 dataset 폴더를 선택하세요.")
            return
        if not self.output_row.edit.text().strip():
            QMessageBox.warning(self, "입력 확인", "Export 출력 폴더를 선택하세요.")
            return
        workspace_text = self.workspace_row.edit.text().strip()
        frame_ids = tuple(item.strip() for item in self.frames.text().split(",") if item.strip())
        config = load_config(self.config_path)
        result = _run_task(
            self,
            "라벨 내보내기",
            lambda: export_dataset_labels(
                dataset,
                config=config,
                export_format=self.format_combo.currentText(),
                output=output,
                frame_ids=frame_ids or None,
                workspace_root=Path(workspace_text) if workspace_text else None,
            ),
        )
        if result is None:
            return
        QMessageBox.information(
            self,
            "Export 완료",
            f"{result.frame_count}개 프레임\n{result.output}",
        )
        self.accept()


class CalibrationVerificationDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calibration 검증")
        self.resize(650, 260)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.dataset_row = _PathRow(self._browse_dataset)
        self.calibration_row = _PathRow(self._browse_calibration)
        self.output_row = _PathRow(self._browse_output)
        self.frames = QLineEdit()
        self.frames.setPlaceholderText("비우면 대표 프레임 자동 선택")
        form.addRow("Dataset", self.dataset_row)
        form.addRow("Calibration YAML", self.calibration_row)
        form.addRow("Frame ID", self.frames)
        form.addRow("검증 결과", self.output_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.setText("검증")
        apply_button.clicked.connect(self._verify)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_dataset(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "검증할 dataset 선택")
        if selected:
            self.dataset_row.edit.setText(selected)

    def _browse_calibration(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "원본 Calibration YAML 폴더 선택")
        if selected:
            self.calibration_row.edit.setText(selected)

    def _browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "검증 결과 폴더 선택")
        if selected:
            self.output_row.edit.setText(selected)

    def _verify(self) -> None:
        dataset = Path(self.dataset_row.edit.text().strip())
        calibration = Path(self.calibration_row.edit.text().strip())
        output = Path(self.output_row.edit.text().strip())
        if not (dataset / "dataset.json").is_file():
            QMessageBox.warning(self, "입력 확인", "dataset.json이 있는 폴더를 선택하세요.")
            return
        if not calibration.is_dir():
            QMessageBox.warning(self, "입력 확인", "Calibration YAML 폴더를 선택하세요.")
            return
        if not self.output_row.edit.text().strip():
            QMessageBox.warning(self, "입력 확인", "검증 결과 폴더를 선택하세요.")
            return
        frame_ids = tuple(item.strip() for item in self.frames.text().split(",") if item.strip())
        result = _run_task(
            self,
            "Calibration 검증",
            lambda: verify_calibration(
                dataset,
                calibration,
                frames=frame_ids,
                write_overlays=True,
                overlay_dir=output,
                report_output=output / "summary.json",
            ),
        )
        if result is None:
            return
        icon = (
            QMessageBox.Icon.Warning
            if result.error_count or result.warning_count
            else QMessageBox.Icon.Information
        )
        message = QMessageBox(
            icon,
            "Calibration 검증",
            f"오류 {result.error_count}개 · 경고 {result.warning_count}개\n"
            f"결과: {result.report_output}\nOverlay: {result.overlay_dir}",
            parent=self,
        )
        message.setDetailedText(json.dumps(result.report, ensure_ascii=False, indent=2))
        message.exec()
        if result.error_count == 0:
            self.accept()


class WorkflowDialog(QDialog):
    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path
        self.selected_dataset: Path | None = None
        self.setWindowTitle("LiDAR Label Tool")
        self.setMinimumSize(580, 380)
        layout = QVBoxLayout(self)
        title = QLabel("LiDAR Label Tool")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)

        grid = QGridLayout()
        actions = (
            ("데이터셋 열기", self._open_dataset, QStyle.StandardPixmap.SP_DialogOpenButton),
            ("원본 데이터 변환", lambda: self._conversion("convert"), QStyle.StandardPixmap.SP_ArrowForward),
            ("기존 데이터 재동기화", lambda: self._conversion("resync"), QStyle.StandardPixmap.SP_BrowserReload),
            ("Calibration JSON 생성", lambda: self._conversion("calibration"), QStyle.StandardPixmap.SP_FileDialogNewFolder),
            ("Calibration 검증", self._verify_calibration, QStyle.StandardPixmap.SP_DialogApplyButton),
            ("데이터셋 검사", self._preflight, QStyle.StandardPixmap.SP_DialogApplyButton),
            ("라벨 통계", self._statistics, QStyle.StandardPixmap.SP_FileDialogInfoView),
            ("라벨 내보내기", self._export, QStyle.StandardPixmap.SP_DialogSaveButton),
            ("정보", self._about, QStyle.StandardPixmap.SP_MessageBoxInformation),
        )
        for index, (text, handler, icon) in enumerate(actions):
            button = QPushButton(text)
            button.setIcon(self.style().standardIcon(icon))
            button.setMinimumHeight(52)
            button.clicked.connect(handler)
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addStretch(1)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.reject)
        layout.addWidget(close_button)

    def _choose_dataset(self, title: str) -> Path | None:
        selected = QFileDialog.getExistingDirectory(self, title)
        return Path(selected) if selected else None

    def _open_dataset(self) -> None:
        selected = self._choose_dataset("LiDAR 데이터셋 폴더 선택")
        if selected is not None:
            self.selected_dataset = selected
            self.accept()

    def _conversion(self, mode: str) -> None:
        dialog = OneChipConversionDialog(self, mode)
        dialog.exec()
        if dialog.selected_dataset is not None:
            self.selected_dataset = dialog.selected_dataset
            self.accept()

    def _preflight(self) -> None:
        dataset = self._choose_dataset("검사할 데이터셋 선택")
        if dataset is None:
            return
        config = load_config(self.config_path)
        report = _run_task(
            self,
            "데이터셋 검사",
            lambda: validate_dataset(
                dataset,
                class_mapping=config["source_class_mappings"],
                verify_images=True,
            ),
        )
        if report is None:
            return
        details = "\n".join(
            f"[{issue.severity}] {issue.code} {issue.frame_id or ''} "
            f"{issue.sensor_id or ''}: {issue.message}"
            for issue in report.issues
        )
        icon = (
            QMessageBox.Icon.Warning
            if report.error_count or report.warning_count
            else QMessageBox.Icon.Information
        )
        message = QMessageBox(icon, "데이터셋 검사", report.short_summary_ko(), parent=self)
        message.setDetailedText(details or "문제 없음")
        message.exec()

    def _verify_calibration(self) -> None:
        CalibrationVerificationDialog(self).exec()

    def _statistics(self) -> None:
        dataset = self._choose_dataset("통계를 확인할 데이터셋 선택")
        if dataset is None:
            return
        config = load_config(self.config_path)
        source = _run_task(
            self,
            "라벨 통계",
            lambda: collect_label_statistics(
                dataset,
                class_mapping=config["source_class_mappings"],
                working=False,
            ),
        )
        if source is None:
            return
        working = _run_task(
            self,
            "작업 라벨 통계",
            lambda: collect_label_statistics(
                dataset,
                class_mapping=config["source_class_mappings"],
                working=True,
            ),
        )
        if working is None:
            return
        message = QMessageBox(
            QMessageBox.Icon.Information,
            "라벨 통계",
            f"프레임 {source.frame_count}개\n"
            f"Source 객체 {source.object_count}개\n"
            f"Working 객체 {working.object_count}개\n"
            f"Reviewed {dict(working.status_counts).get('reviewed', 0)}개",
            parent=self,
        )
        message.setDetailedText(
            json.dumps(
                {"source": source.to_dict(), "working": working.to_dict()},
                ensure_ascii=False,
                indent=2,
            )
        )
        message.exec()

    def _export(self) -> None:
        LabelExportDialog(self, self.config_path).exec()

    def _about(self) -> None:
        frozen_root = getattr(sys, "_MEIPASS", None)
        notice_path = (
            Path(frozen_root) / "THIRD_PARTY_NOTICES.md"
            if frozen_root
            else Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md"
        )
        notices = (
            notice_path.read_text(encoding="utf-8")
            if notice_path.is_file()
            else "Third-party notice file is unavailable."
        )
        message = QMessageBox(
            QMessageBox.Icon.Information,
            "LiDAR Label Tool",
            f"Version {__version__}",
            parent=self,
        )
        message.setDetailedText(notices)
        message.exec()
