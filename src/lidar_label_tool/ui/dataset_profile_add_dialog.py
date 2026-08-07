from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.domain.dataset_v2 import DatasetProfileV2
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.services.dataset_discovery import (
    DatasetDiscoveryResult,
    SensorCandidate,
    discover_dataset,
)
from lidar_label_tool.services.dataset_profile_add_v2 import (
    DatasetProfileAddAnalysis,
    DatasetProfileAddRequest,
    DatasetProfileAddResult,
    add_dataset_profile_v2,
    analyze_dataset_profile_add_v2,
)
from lidar_label_tool.services.dataset_setup import CameraSetup, LidarSetup, TimestampSetup


class _ProfileAddBridge(QObject):
    analysis_completed = Signal(object)
    analysis_discarded = Signal()
    addition_completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, int, int, str)


class DatasetProfileAddDialog(QDialog):
    """Analyze and atomically add one LiDAR profile to an existing v2 dataset."""

    def __init__(
        self,
        config_root: Path,
        parent: QWidget | None = None,
        *,
        discovery_result: DatasetDiscoveryResult | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_root = Path(config_root).resolve()
        self.manifest = load_dataset_manifest_v2(self.config_root)
        default_adapter = DeviceCentricV2Adapter(
            self.config_root,
            self.manifest.default_profile_id,
        )
        default_adapter.scan()
        self.data_root = default_adapter.data_root
        self.discovery = discovery_result or discover_dataset(self.data_root)
        registered_patterns = {item.data_pattern for item in self.manifest.lidars}
        self.available_lidars = tuple(
            item
            for item in self.discovery.lidars
            if item.data_pattern not in registered_patterns
        )
        self.camera_candidate = self._existing_camera_candidate()
        self.analysis: DatasetProfileAddAnalysis | None = None
        self.add_result: DatasetProfileAddResult | None = None
        self.selected_profile_id: str | None = None
        self._configuration_generation = 0
        self._busy = False
        self._cancel = Event()
        self._executor_shutdown = False
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="dataset-profile-add",
        )
        self._bridge = _ProfileAddBridge(self)
        self._bridge.analysis_completed.connect(self._on_analysis_completed)
        self._bridge.analysis_discarded.connect(self._on_analysis_discarded)
        self._bridge.addition_completed.connect(self._on_addition_completed)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.progress.connect(self._on_progress)
        self._build_ui()
        self._populate_lidar_fields()

    def _build_ui(self) -> None:
        self.setWindowTitle("범용 v2 LiDAR profile 추가")
        self.resize(780, 660)
        layout = QVBoxLayout(self)
        description = QLabel(
            "기존 dataset ID, profile, 라벨과 generation은 유지합니다. 새 LiDAR를 분석한 뒤 "
            "모든 index를 새 generation에 기록하고 dataset.json을 마지막에 교체합니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        summary = QLabel(
            f"Dataset: {self.manifest.display_name} ({self.manifest.dataset_id})\n"
            f"현재 revision: {self.manifest.manifest_revision} · "
            f"기존 profile: {', '.join(item.id for item in self.manifest.profiles)}\n"
            f"원본: {self.data_root}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QFormLayout()
        self.lidar_combo = QComboBox()
        for candidate in self.available_lidars:
            self.lidar_combo.addItem(
                f"{candidate.display_name} · {candidate.format.upper()} · "
                f"{candidate.sample_count} frames",
                candidate.key,
            )
        self.lidar_combo.currentIndexChanged.connect(self._populate_lidar_fields)
        form.addRow("추가할 LiDAR", self.lidar_combo)

        self.sensor_id_edit = QLineEdit()
        self.sensor_id_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Sensor ID", self.sensor_id_edit)
        self.coordinate_frame_edit = QLineEdit()
        self.coordinate_frame_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Coordinate frame", self.coordinate_frame_edit)
        self.point_columns_edit = QLineEdit()
        self.point_columns_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Point columns", self.point_columns_edit)
        self.profile_id_edit = QLineEdit()
        self.profile_id_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Profile ID", self.profile_id_edit)
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Profile 표시 이름", self.profile_name_edit)

        self.use_camera_check = QCheckBox("기존 카메라와 연결")
        self.use_camera_check.setEnabled(self.camera_candidate is not None)
        self.use_camera_check.setChecked(self.camera_candidate is not None)
        self.use_camera_check.toggled.connect(self._update_sync_fields)
        form.addRow("카메라", self.use_camera_check)
        self.sync_method_combo = QComboBox()
        self.sync_method_combo.addItem("LiDAR만 사용", "lidar_only")
        self.sync_method_combo.addItem("같은 파일 stem", "exact_stem")
        self.sync_method_combo.addItem("가장 가까운 timestamp", "timestamp_nearest")
        self.sync_method_combo.currentIndexChanged.connect(self._update_sync_fields)
        form.addRow("동기화", self.sync_method_combo)

        self.timestamp_combo = QComboBox()
        self.timestamp_combo.addItem("사용 안 함", None)
        for item in self.discovery.timestamps:
            if item.read_error is None:
                self.timestamp_combo.addItem(item.relative_path, item.relative_path)
        self.timestamp_combo.currentIndexChanged.connect(self._timestamp_selected)
        form.addRow("LiDAR timestamp CSV", self.timestamp_combo)
        self.sample_column_edit = QLineEdit("sample_id")
        self.sample_column_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Sample ID 컬럼", self.sample_column_edit)
        self.value_column_edit = QLineEdit("timestamp_ns")
        self.value_column_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Timestamp 컬럼", self.value_column_edit)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["ns", "us", "ms", "s"])
        self.unit_combo.currentIndexChanged.connect(self._configuration_changed)
        form.addRow("Timestamp 단위", self.unit_combo)
        self.clock_domain_edit = QLineEdit("bag")
        self.clock_domain_edit.textChanged.connect(self._configuration_changed)
        form.addRow("Clock domain", self.clock_domain_edit)
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 60_000.0)
        self.tolerance_spin.setDecimals(6)
        self.tolerance_spin.setSuffix(" ms")
        self.tolerance_spin.setValue(self._default_tolerance_ms())
        self.tolerance_spin.valueChanged.connect(self._configuration_changed)
        form.addRow("Nearest tolerance", self.tolerance_spin)
        layout.addLayout(form)

        self.coordinate_confirm = QCheckBox(
            "추가 LiDAR가 meter / x-forward / y-left / z-up이며 box yaw가 +z 기준임을 확인했습니다."
        )
        self.coordinate_confirm.toggled.connect(self._configuration_changed)
        layout.addWidget(self.coordinate_confirm)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.analysis_button = self.buttons.addButton(
            "변경 분석",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.analysis_button.clicked.connect(self._start_analysis)
        self.add_button = self.buttons.addButton(
            "새 profile 추가",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.add_button.clicked.connect(self._start_addition)
        self.buttons.rejected.connect(self._cancel_or_close)
        layout.addWidget(self.buttons)
        self._update_sync_fields()

    def _existing_camera_candidate(self) -> SensorCandidate | None:
        if self.manifest.camera is None:
            return None
        return next(
            (
                item
                for item in self.discovery.cameras
                if item.data_pattern == self.manifest.camera.image_pattern
            ),
            None,
        )

    def _default_tolerance_ms(self) -> float:
        profile = self._default_profile()
        if profile.frame_index.generation.tolerance_ns is None:
            return 50.0
        return profile.frame_index.generation.tolerance_ns / 1_000_000

    def _default_profile(self) -> DatasetProfileV2:
        profile = self.manifest.profile(self.manifest.default_profile_id)
        if profile is None:
            raise ValueError("default_profile_id does not reference an existing profile")
        return profile

    def _selected_candidate(self) -> SensorCandidate | None:
        key = self.lidar_combo.currentData()
        return next((item for item in self.available_lidars if item.key == key), None)

    def _populate_lidar_fields(self, *_args: object) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self.status_label.setText("추가할 수 있는 미등록 LiDAR 후보가 없습니다.")
            self._configuration_changed()
            return
        self.sensor_id_edit.setText(candidate.suggested_id)
        self.coordinate_frame_edit.setText(f"lidar:{candidate.suggested_id}")
        self.point_columns_edit.setText(",".join(candidate.declared_point_columns))
        self.point_columns_edit.setToolTip(
            (
                f"명시적 metadata에서 읽음: {candidate.metadata_relative_path}"
                if candidate.metadata_relative_path is not None
                else "metadata가 없어 사용자가 정확한 전체 열 순서를 입력해야 합니다."
            )
        )
        self.profile_id_edit.setText(f"{candidate.suggested_id}_profile")
        self.profile_name_edit.setText(f"{candidate.display_name} 라벨링")
        self._select_matching_timestamp(candidate)
        default_method = self._default_profile().frame_index.generation.method
        method_index = self.sync_method_combo.findData(default_method)
        if self.camera_candidate is not None and method_index >= 0:
            self.sync_method_combo.setCurrentIndex(method_index)
        self.status_label.setText(
            f"{candidate.display_name} metadata와 timestamp 설정을 확인한 뒤 변경 분석을 실행하세요."
        )
        self._configuration_changed()

    def _select_matching_timestamp(self, candidate: SensorCandidate) -> None:
        target_names = {
            f"{candidate.display_name}.csv".casefold(),
            f"{candidate.suggested_id}.csv".casefold(),
        }
        for index in range(1, self.timestamp_combo.count()):
            value = str(self.timestamp_combo.itemData(index))
            if Path(value).name.casefold() in target_names:
                self.timestamp_combo.setCurrentIndex(index)
                self._apply_timestamp_suggestion(value)
                return
        self.timestamp_combo.setCurrentIndex(0)

    def _timestamp_selected(self, *_args: object) -> None:
        value = self.timestamp_combo.currentData()
        if value is not None:
            self._apply_timestamp_suggestion(str(value))
        self._configuration_changed()

    def _apply_timestamp_suggestion(self, relative_path: str) -> None:
        candidate = next(
            (
                item
                for item in self.discovery.timestamps
                if item.relative_path == relative_path
            ),
            None,
        )
        if candidate is None:
            return
        columns = set(candidate.columns)
        if "sample_id" in columns:
            self.sample_column_edit.setText("sample_id")
        camera_timestamp = self.manifest.camera.timestamp if self.manifest.camera else None
        preferred = (
            camera_timestamp.value_column
            if camera_timestamp is not None
            else "bag_time_ns"
        )
        if preferred in columns:
            self.value_column_edit.setText(preferred)
            if camera_timestamp is not None:
                self.unit_combo.setCurrentText(camera_timestamp.unit)
                self.clock_domain_edit.setText(camera_timestamp.clock_domain)
            elif preferred.endswith("_ns"):
                self.unit_combo.setCurrentText("ns")
                self.clock_domain_edit.setText(
                    "bag" if preferred == "bag_time_ns" else "unspecified"
                )

    def build_request(self) -> DatasetProfileAddRequest:
        candidate = self._selected_candidate()
        if candidate is None:
            raise ValueError("추가할 LiDAR 후보가 없습니다.")
        method = str(self.sync_method_combo.currentData())
        timestamp = None
        if method == "timestamp_nearest":
            relative_path = self.timestamp_combo.currentData()
            if relative_path is None:
                raise ValueError("LiDAR timestamp CSV를 선택해야 합니다.")
            timestamp = TimestampSetup(
                relative_path=str(relative_path),
                sample_id_column=self.sample_column_edit.text().strip(),
                value_column=self.value_column_edit.text().strip(),
                unit=self.unit_combo.currentText(),  # type: ignore[arg-type]
                clock_domain=self.clock_domain_edit.text().strip(),
            )
        columns = tuple(
            value.strip()
            for value in self.point_columns_edit.text().split(",")
            if value.strip()
        )
        lidar = LidarSetup(
            candidate=candidate,
            sensor_id=self.sensor_id_edit.text().strip(),
            display_name=candidate.display_name,
            coordinate_frame=self.coordinate_frame_edit.text().strip(),
            point_columns=columns,
            profile_id=self.profile_id_edit.text().strip(),
            profile_display_name=self.profile_name_edit.text().strip(),
            sync_method=method,  # type: ignore[arg-type]
            tolerance_ns=(
                round(self.tolerance_spin.value() * 1_000_000)
                if method == "timestamp_nearest"
                else None
            ),
            timestamp=timestamp,
        )
        camera = None
        if method != "lidar_only" and self.use_camera_check.isChecked():
            if self.camera_candidate is None or self.manifest.camera is None:
                raise ValueError("기존 manifest의 카메라 파일을 찾지 못했습니다.")
            camera = CameraSetup(
                candidate=self.camera_candidate,
                sensor_id=self.manifest.camera.id,
                display_name=self.manifest.camera.display_name,
                coordinate_frame=self.manifest.camera.coordinate_frame,
            )
        return DatasetProfileAddRequest(
            config_root=self.config_root,
            lidar=lidar,
            camera=camera,
            coordinate_system_confirmed=self.coordinate_confirm.isChecked(),
        )

    def _start_analysis(self) -> None:
        try:
            request = self.build_request()
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "추가 설정 확인 필요", str(exc))
            return
        self.analysis = None
        self._cancel.clear()
        request_generation = self._configuration_generation
        self._set_busy(True)
        future = self._executor.submit(
            analyze_dataset_profile_add_v2,
            request,
            progress=self._emit_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(
            lambda completed: self._finish_future(
                "analysis", completed, request_generation
            )
        )

    def _start_addition(self) -> None:
        if self.analysis is None:
            QMessageBox.warning(self, "변경 분석 필요", "현재 설정을 먼저 분석해 주세요.")
            return
        try:
            request = replace(
                self.build_request(),
                expected_manifest_sha256=self.analysis.manifest_sha256,
                expected_source_inventory_sha256=(
                    self.analysis.source_inventory_sha256
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "추가 설정 확인 필요", str(exc))
            return
        self._cancel.clear()
        self._set_busy(True)
        future = self._executor.submit(
            add_dataset_profile_v2,
            request,
            progress=self._emit_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(
            lambda completed: self._finish_future("addition", completed)
        )

    def _finish_future(
        self,
        operation: str,
        future: Future[Any],
        request_generation: int | None = None,
    ) -> None:
        try:
            value = future.result()
        except Exception as exc:
            self._bridge.failed.emit(operation, f"{type(exc).__name__}: {exc}")
            return
        if operation == "analysis":
            if request_generation != self._configuration_generation:
                self._bridge.analysis_discarded.emit()
                return
            self._bridge.analysis_completed.emit(value)
        else:
            self._bridge.addition_completed.emit(value)

    def _emit_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self._bridge.progress.emit(phase, current, total, message)

    def _on_analysis_completed(self, result_object: object) -> None:
        if not isinstance(result_object, DatasetProfileAddAnalysis):
            self._on_failed("analysis", "unexpected profile-add analysis result")
            return
        self.analysis = result_object
        self._set_busy(False)
        qa = result_object.qa
        delta = (
            "-"
            if qa.max_abs_delta_ns is None
            else f"{qa.max_abs_delta_ns / 1_000_000:.3f} ms"
        )
        self.status_label.setText(
            f"분석 완료 · revision {result_object.current_manifest_revision} → "
            f"{result_object.next_manifest_revision}\n"
            f"LiDAR {qa.lidar_frame_count}, camera matched {qa.matched_camera_count}, "
            f"unmatched {qa.unmatched_camera_count}, reuse {qa.camera_sample_reuse_count}, "
            f"max delta {delta}\n"
            f"기존 라벨 {result_object.existing_label_count}개는 그대로 유지됩니다."
        )

    def _on_analysis_discarded(self) -> None:
        self.analysis = None
        self._set_busy(False)
        self.status_label.setText(
            "분석 중 설정이 변경되어 결과를 폐기했습니다. 다시 분석해 주세요."
        )

    def _on_addition_completed(self, result_object: object) -> None:
        if not isinstance(result_object, DatasetProfileAddResult):
            self._on_failed("addition", "unexpected profile-add result")
            return
        self.add_result = result_object
        self.selected_profile_id = result_object.profile_id
        self._set_busy(False)
        self.accept()

    def _on_failed(self, operation: str, message: str) -> None:
        self._set_busy(False)
        if self._cancel.is_set():
            self.status_label.setText("작업을 취소했습니다. 기존 구성은 유지됩니다.")
            return
        self.status_label.setText(f"{operation} 실패: {message}")
        QMessageBox.critical(
            self,
            "LiDAR profile 추가 실패",
            f"{message}\n\n기존 dataset.json, generation과 라벨은 유지됩니다.",
        )

    def _on_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{phase} · {current}/{total} · {message}")

    def _update_sync_fields(self, *_args: object) -> None:
        has_camera = self.use_camera_check.isChecked() and self.camera_candidate is not None
        if not has_camera and self.sync_method_combo.currentData() != "lidar_only":
            self.sync_method_combo.setCurrentIndex(0)
        elif has_camera and self.sync_method_combo.currentData() == "lidar_only":
            default_method = self._default_profile().frame_index.generation.method
            target = default_method if default_method != "lidar_only" else "exact_stem"
            index = self.sync_method_combo.findData(target)
            if index >= 0:
                self.sync_method_combo.setCurrentIndex(index)
        timestamp_mode = (
            has_camera and self.sync_method_combo.currentData() == "timestamp_nearest"
        )
        for widget in (
            self.timestamp_combo,
            self.sample_column_edit,
            self.value_column_edit,
            self.unit_combo,
            self.clock_domain_edit,
            self.tolerance_spin,
        ):
            widget.setEnabled(timestamp_mode and not self._busy)
        self._configuration_changed()

    def _configuration_changed(self, *_args: object) -> None:
        self._configuration_generation += 1
        if self.analysis is not None:
            self.analysis = None
            self.status_label.setText(
                "설정이 변경되었습니다. 추가하기 전에 다시 분석해 주세요."
            )
        self._update_buttons()

    def _configuration_ready(self) -> bool:
        candidate = self._selected_candidate()
        columns = {
            value.strip()
            for value in self.point_columns_edit.text().split(",")
            if value.strip()
        }
        timestamp_ready = True
        if self.sync_method_combo.currentData() == "timestamp_nearest":
            timestamp_ready = (
                self.timestamp_combo.currentData() is not None
                and bool(self.sample_column_edit.text().strip())
                and bool(self.value_column_edit.text().strip())
                and bool(self.clock_domain_edit.text().strip())
            )
        return (
            candidate is not None
            and bool(self.sensor_id_edit.text().strip())
            and bool(self.coordinate_frame_edit.text().strip())
            and bool(self.profile_id_edit.text().strip())
            and bool(self.profile_name_edit.text().strip())
            and {"x", "y", "z"}.issubset(columns)
            and timestamp_ready
            and self.coordinate_confirm.isChecked()
        )

    def _update_buttons(self) -> None:
        ready = self._configuration_ready()
        self.analysis_button.setEnabled(ready and not self._busy)
        self.add_button.setEnabled(ready and self.analysis is not None and not self._busy)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.lidar_combo,
            self.sensor_id_edit,
            self.coordinate_frame_edit,
            self.point_columns_edit,
            self.profile_id_edit,
            self.profile_name_edit,
            self.use_camera_check,
            self.sync_method_combo,
            self.timestamp_combo,
            self.sample_column_edit,
            self.value_column_edit,
            self.unit_combo,
            self.clock_domain_edit,
            self.tolerance_spin,
            self.coordinate_confirm,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self.use_camera_check.setEnabled(self.camera_candidate is not None)
            timestamp_mode = (
                self.use_camera_check.isChecked()
                and self.sync_method_combo.currentData() == "timestamp_nearest"
            )
            for widget in (
                self.timestamp_combo,
                self.sample_column_edit,
                self.value_column_edit,
                self.unit_combo,
                self.clock_domain_edit,
                self.tolerance_spin,
            ):
                widget.setEnabled(timestamp_mode)
        self.progress_bar.setRange(0, 0 if busy else 1)
        self._update_buttons()

    def _cancel_or_close(self) -> None:
        self._cancel.set()
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
