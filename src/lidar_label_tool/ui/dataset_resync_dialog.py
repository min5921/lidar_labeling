from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.services.dataset_resync_v2 import (
    DatasetResyncAnalysis,
    DatasetResyncRequest,
    DatasetResyncResult,
    analyze_dataset_resync_v2,
    resynchronize_dataset_v2,
)


class _ResyncBridge(QObject):
    analysis_completed = Signal(object)
    apply_completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, int, int, str)


class DatasetResyncV2Dialog(QDialog):
    """Preview and atomically apply a generic v2 synchronization generation."""

    def __init__(self, config_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_root = Path(config_root).resolve()
        self.manifest = load_dataset_manifest_v2(self.config_root)
        self.analysis: DatasetResyncAnalysis | None = None
        self.resync_result: DatasetResyncResult | None = None
        self._cancel = Event()
        self._busy = False
        self._executor_shutdown = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-resync")
        self._bridge = _ResyncBridge(self)
        self._bridge.analysis_completed.connect(self._on_analysis_completed)
        self._bridge.apply_completed.connect(self._on_apply_completed)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.progress.connect(self._on_progress)
        self._build_ui()
        self._load_profile_settings()

    def _build_ui(self) -> None:
        self.setWindowTitle("범용 데이터셋 v2 재동기화")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        introduction = QLabel(
            "LiDAR frame과 라벨 namespace는 유지하고 카메라 연결만 새 generation으로 "
            "계산합니다. 분석 결과를 확인하기 전에는 dataset.json을 변경하지 않습니다."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        form = QFormLayout()
        form.addRow("구성 폴더", QLabel(str(self.config_root)))
        self.profile_combo = QComboBox()
        for profile in self.manifest.profiles:
            self.profile_combo.addItem(
                f"{profile.display_name} ({profile.id})",
                profile.id,
            )
        default_index = next(
            (
                index
                for index, profile in enumerate(self.manifest.profiles)
                if profile.id == self.manifest.default_profile_id
            ),
            0,
        )
        self.profile_combo.setCurrentIndex(default_index)
        self.profile_combo.currentIndexChanged.connect(self._load_profile_settings)
        form.addRow("기준 profile", self.profile_combo)

        self.method_combo = QComboBox()
        self.method_combo.addItem("LiDAR만 사용", "lidar_only")
        self.method_combo.addItem("같은 파일 stem", "exact_stem")
        self.method_combo.addItem("가장 가까운 timestamp", "timestamp_nearest")
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        form.addRow("동기화 방식", self.method_combo)

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 60_000.0)
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setSuffix(" ms")
        self.tolerance_spin.valueChanged.connect(self._invalidate_analysis)
        form.addRow("Nearest tolerance", self.tolerance_spin)
        layout.addLayout(form)

        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText(
            "‘변경 분석’을 누르면 profile별 match 수, 누락 수, camera binding 변경 수를 표시합니다."
        )
        layout.addWidget(self.summary, 1)

        self.status_label = QLabel("아직 파일을 변경하지 않았습니다.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.analyze_button = self.buttons.addButton(
            "변경 분석",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.apply_button = self.buttons.addButton(
            "새 generation 적용",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.apply_button.setEnabled(False)
        self.analyze_button.clicked.connect(self._start_analysis)
        self.apply_button.clicked.connect(self._start_apply)
        self.buttons.rejected.connect(self._cancel_or_close)
        layout.addWidget(self.buttons)

    def _selected_profile(self) -> str:
        return str(self.profile_combo.currentData())

    def _selected_method(self) -> str:
        return str(self.method_combo.currentData())

    def _selected_tolerance_ns(self) -> int | None:
        if self._selected_method() != "timestamp_nearest":
            return None
        return round(self.tolerance_spin.value() * 1_000_000)

    def _load_profile_settings(self) -> None:
        profile = self.manifest.profile(self._selected_profile())
        if profile is None:
            return
        method = profile.frame_index.generation.method
        index = self.method_combo.findData(method)
        self.method_combo.blockSignals(True)
        self.method_combo.setCurrentIndex(index)
        self.method_combo.blockSignals(False)
        tolerance_ns = profile.frame_index.generation.tolerance_ns
        self.tolerance_spin.blockSignals(True)
        self.tolerance_spin.setValue((tolerance_ns or 50_000_000) / 1_000_000)
        self.tolerance_spin.blockSignals(False)
        self._method_changed()

    def _method_changed(self) -> None:
        self.tolerance_spin.setEnabled(self._selected_method() == "timestamp_nearest")
        self._invalidate_analysis()

    def _invalidate_analysis(self) -> None:
        self.analysis = None
        self.apply_button.setEnabled(False)
        if not self._busy:
            self.status_label.setText("설정이 바뀌었습니다. 다시 분석하세요.")

    def _request(self, *, use_analysis_fingerprints: bool) -> DatasetResyncRequest:
        analysis = self.analysis if use_analysis_fingerprints else None
        return DatasetResyncRequest(
            config_root=self.config_root,
            profile_id=self._selected_profile(),
            method=self._selected_method(),  # type: ignore[arg-type]
            tolerance_ns=self._selected_tolerance_ns(),
            expected_manifest_sha256=(analysis.manifest_sha256 if analysis else None),
            expected_source_inventory_sha256=(
                analysis.source_inventory_sha256 if analysis else None
            ),
        )

    def _start_analysis(self) -> None:
        self._cancel.clear()
        self._set_busy(True)
        future = self._executor.submit(
            analyze_dataset_resync_v2,
            self._request(use_analysis_fingerprints=False),
            progress=self._emit_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(lambda completed: self._finish_future("analysis", completed))

    def _start_apply(self) -> None:
        if self.analysis is None:
            return
        self._cancel.clear()
        self._set_busy(True)
        future = self._executor.submit(
            resynchronize_dataset_v2,
            self._request(use_analysis_fingerprints=True),
            progress=self._emit_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(lambda completed: self._finish_future("apply", completed))

    def _finish_future(self, operation: str, future: Future[Any]) -> None:
        try:
            value = future.result()
        except Exception as exc:
            self._bridge.failed.emit(operation, f"{type(exc).__name__}: {exc}")
            return
        if operation == "analysis":
            self._bridge.analysis_completed.emit(value)
        else:
            self._bridge.apply_completed.emit(value)

    def _emit_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self._bridge.progress.emit(phase, current, total, message)

    def _on_analysis_completed(self, value: object) -> None:
        if not isinstance(value, DatasetResyncAnalysis):
            self._on_failed("analysis", "unexpected analysis result")
            return
        self.analysis = value
        lines = [
            f"Manifest revision: {value.current_manifest_revision} → {value.next_manifest_revision}",
            "LiDAR frame/sample/path binding 변경: 0 (고정)",
            "",
        ]
        for profile in value.profiles:
            lines.extend(
                [
                    f"[{profile.profile_id}] {profile.method}",
                    f"  LiDAR frames: {profile.qa.lidar_frame_count}",
                    f"  Camera matched/unmatched: "
                    f"{profile.qa.matched_camera_count}/{profile.qa.unmatched_camera_count}",
                    f"  Camera binding 변경: {profile.camera_binding_change_count}",
                    f"  Frame 순서 위치 변경: {profile.frame_order_change_count}",
                    f"  Camera reuse/max run: {profile.qa.camera_sample_reuse_count}/"
                    f"{profile.qa.max_camera_repeat_run}",
                    "",
                ]
            )
        self.summary.setPlainText("\n".join(lines).rstrip())
        self._set_busy(False)
        self.apply_button.setEnabled(True)
        self.status_label.setText(
            "분석 완료. 적용 전까지 기존 dataset.json과 frame index는 그대로입니다."
        )

    def _on_apply_completed(self, value: object) -> None:
        if not isinstance(value, DatasetResyncResult):
            self._on_failed("apply", "unexpected resync result")
            return
        self.resync_result = value
        self._set_busy(False)
        QMessageBox.information(
            self,
            "재동기화 완료",
            f"Manifest revision {value.manifest_revision}을 활성화했습니다.\n"
            f"새 generation: {value.generation_path}\n"
            "기존 generation과 LiDAR 라벨은 보존되었습니다.",
        )
        self.accept()

    def _on_failed(self, operation: str, message: str) -> None:
        self._set_busy(False)
        if self._cancel.is_set():
            self.status_label.setText("작업을 취소했습니다. 기존 generation은 유지됩니다.")
            return
        self.status_label.setText(f"{operation} 실패: {message}")
        QMessageBox.critical(
            self,
            "재동기화 실패",
            f"{message}\n\n이전 dataset.json과 generation은 계속 활성 상태입니다.",
        )

    def _on_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{phase} · {current}/{total} · {message}")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.profile_combo,
            self.method_combo,
            self.tolerance_spin,
            self.analyze_button,
        ):
            widget.setEnabled(not busy)
        self.tolerance_spin.setEnabled(
            not busy and self._selected_method() == "timestamp_nearest"
        )
        self.apply_button.setEnabled(not busy and self.analysis is not None)
        if busy:
            self.progress_bar.setRange(0, 0)

    def _cancel_or_close(self) -> None:
        if self._busy:
            self._cancel.set()
            self.status_label.setText("취소 요청 중…")
            return
        self.reject()

    def _shutdown_executor(self) -> None:
        if self._executor_shutdown:
            return
        self._executor_shutdown = True
        self._cancel.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def done(self, result: int) -> None:
        self._shutdown_executor()
        super().done(result)

    def closeEvent(self, event: Any) -> None:
        self._shutdown_executor()
        super().closeEvent(event)
