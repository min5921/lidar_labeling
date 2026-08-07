from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, Mapping

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.services.dataset_discovery import (
    DatasetDiscoveryResult,
    discover_dataset,
)
from lidar_label_tool.services.dataset_setup import (
    CameraSetup,
    DatasetSetupAnalysis,
    DatasetSetupRequest,
    DatasetSetupResult,
    LidarSetup,
    TimestampSetup,
    analyze_generic_dataset,
    create_generic_dataset,
    new_dataset_id,
    taxonomy_from_config,
)


class _SetupBridge(QObject):
    discovery_completed = Signal(object)
    analysis_completed = Signal(object)
    analysis_discarded = Signal()
    setup_completed = Signal(object)
    failed = Signal(str, str)
    progress = Signal(str, int, int, str)


class DatasetSetupDialog(QDialog):
    """Collect explicit choices and delegate all files to DatasetSetupService."""

    def __init__(
        self,
        source_root: Path,
        config: Mapping[str, Any],
        parent: QWidget | None = None,
        *,
        discovery_result: DatasetDiscoveryResult | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_root = Path(source_root).resolve()
        self.config = config
        self.discovery: DatasetDiscoveryResult | None = discovery_result
        self.analysis: DatasetSetupAnalysis | None = None
        self.setup_result: DatasetSetupResult | None = None
        self.selected_config_root: Path | None = None
        self.selected_profile_id: str | None = None
        self._cancel = Event()
        self._busy = False
        self._configuration_generation = 0
        self._executor_shutdown = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset-setup")
        self._bridge = _SetupBridge(self)
        self._bridge.discovery_completed.connect(self._on_discovery)
        self._bridge.analysis_completed.connect(self._on_analysis_completed)
        self._bridge.analysis_discarded.connect(self._on_analysis_discarded)
        self._bridge.setup_completed.connect(self._on_setup_completed)
        self._bridge.failed.connect(self._on_failed)
        self._bridge.progress.connect(self._on_progress)
        self._build_ui()
        if discovery_result is None:
            self._start_discovery()
        else:
            self._on_discovery(discovery_result)

    def _build_ui(self) -> None:
        self.setWindowTitle("범용 데이터셋 v2 구성")
        self.resize(980, 720)
        layout = QVBoxLayout(self)
        introduction = QLabel(
            "원본 파일은 이동·변환하지 않습니다. 사용할 LiDAR와 선택적 카메라, 포인트 열, "
            "동기화 기준을 확인한 뒤 외부 구성 파일만 생성합니다."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        form = QFormLayout()
        form.addRow("원본 폴더", QLabel(str(self.source_root)))
        self.display_name_edit = QLineEdit(self.source_root.name)
        form.addRow("표시 이름", self.display_name_edit)
        self.dataset_id_edit = QLineEdit(new_dataset_id())
        self.dataset_id_edit.setReadOnly(True)
        form.addRow("Dataset ID", self.dataset_id_edit)
        config_row = QWidget()
        config_layout = QHBoxLayout(config_row)
        config_layout.setContentsMargins(0, 0, 0, 0)
        self.config_root_edit = QLineEdit(str(self.source_root))
        self.config_browse_button = QPushButton("찾기…")
        self.config_browse_button.clicked.connect(self._browse_config_root)
        config_layout.addWidget(self.config_root_edit, 1)
        config_layout.addWidget(self.config_browse_button)
        form.addRow("구성/라벨 폴더", config_row)
        layout.addLayout(form)

        self.lidar_table = QTableWidget(0, 6)
        self.lidar_table.setHorizontalHeaderLabels(
            ["사용", "LiDAR 후보", "Sensor ID", "Coordinate frame", "Point columns", "Timestamp CSV"]
        )
        self.lidar_table.horizontalHeader().setStretchLastSection(True)
        self.lidar_table.itemChanged.connect(self._configuration_changed)
        layout.addWidget(QLabel("LiDAR — 각 선택 항목은 독립 profile로 생성됩니다."))
        layout.addWidget(self.lidar_table, 1)

        camera_form = QFormLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(self._update_camera_fields)
        camera_form.addRow("카메라 (0~1개)", self.camera_combo)
        self.camera_id_edit = QLineEdit("head_camera")
        camera_form.addRow("Camera ID", self.camera_id_edit)
        self.camera_frame_edit = QLineEdit("camera:head_camera")
        camera_form.addRow("Camera coordinate frame", self.camera_frame_edit)
        self.camera_timestamp_combo = QComboBox()
        camera_form.addRow("Camera timestamp CSV", self.camera_timestamp_combo)
        layout.addLayout(camera_form)

        sync_form = QFormLayout()
        self.sync_method_combo = QComboBox()
        self.sync_method_combo.addItem("LiDAR만 사용", "lidar_only")
        self.sync_method_combo.addItem("같은 파일 stem", "exact_stem")
        self.sync_method_combo.addItem("가장 가까운 timestamp", "timestamp_nearest")
        self.sync_method_combo.currentIndexChanged.connect(self._update_sync_fields)
        sync_form.addRow("동기화", self.sync_method_combo)
        self.sample_column_edit = QLineEdit("sample_id")
        self.sample_column_edit.textChanged.connect(self._configuration_changed)
        sync_form.addRow("Sample ID 컬럼", self.sample_column_edit)
        self.value_column_edit = QLineEdit("timestamp_ns")
        self.value_column_edit.textChanged.connect(self._configuration_changed)
        sync_form.addRow("Timestamp 컬럼", self.value_column_edit)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["ns", "us", "ms", "s"])
        sync_form.addRow("Timestamp 단위", self.unit_combo)
        self.clock_domain_edit = QLineEdit("bag")
        self.clock_domain_edit.textChanged.connect(self._configuration_changed)
        sync_form.addRow("Clock domain", self.clock_domain_edit)
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0, 60_000.0)
        self.tolerance_spin.setDecimals(3)
        self.tolerance_spin.setValue(50.0)
        self.tolerance_spin.setSuffix(" ms")
        sync_form.addRow("Nearest tolerance", self.tolerance_spin)
        layout.addLayout(sync_form)

        self.coordinate_confirm = QCheckBox(
            "모든 선택 LiDAR가 meter / x-forward / y-left / z-up이며 box yaw가 +z 기준임을 확인했습니다."
        )
        self.coordinate_confirm.toggled.connect(self._configuration_changed)
        layout.addWidget(self.coordinate_confirm)

        self.status_label = QLabel("파일을 찾는 중…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.addButton(
            "구성 분석",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._start_analysis)
        self.create_button = self.buttons.addButton(
            "검증 결과로 생성",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.create_button.setEnabled(False)
        self.create_button.clicked.connect(self._start_setup)
        self.buttons.rejected.connect(self._cancel_or_close)
        layout.addWidget(self.buttons)

        self.display_name_edit.textChanged.connect(self._configuration_changed)
        self.config_root_edit.textChanged.connect(self._configuration_changed)
        self.camera_id_edit.textChanged.connect(self._configuration_changed)
        self.camera_frame_edit.textChanged.connect(self._configuration_changed)
        self.unit_combo.currentIndexChanged.connect(self._configuration_changed)
        self.tolerance_spin.valueChanged.connect(self._configuration_changed)

    def _start_discovery(self) -> None:
        self._cancel.clear()
        future = self._executor.submit(
            discover_dataset,
            self.source_root,
            progress=self._emit_discovery_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(lambda completed: self._finish_future("discovery", completed))

    def _emit_discovery_progress(self, current: int, total: int, path: Path) -> None:
        self._bridge.progress.emit("discovery", current, total, str(path))

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
        if operation == "discovery":
            self._bridge.discovery_completed.emit(value)
        elif operation == "analysis":
            if request_generation != self._configuration_generation:
                self._bridge.analysis_discarded.emit()
                return
            self._bridge.analysis_completed.emit(value)
        else:
            self._bridge.setup_completed.emit(value)

    def _on_discovery(self, result_object: object) -> None:
        if not isinstance(result_object, DatasetDiscoveryResult):
            self._on_failed("discovery", "unexpected discovery result")
            return
        self.discovery = result_object
        self._populate_candidates(result_object)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.status_label.setText(
            f"LiDAR {len(result_object.lidars)}개, 카메라 {len(result_object.cameras)}개, "
            f"timestamp CSV {len(result_object.timestamps)}개를 찾았습니다."
        )
        self._update_apply_enabled()

    def _populate_candidates(self, result: DatasetDiscoveryResult) -> None:
        self.lidar_table.setRowCount(len(result.lidars))
        timestamp_names = [item.relative_path for item in result.timestamps if not item.read_error]
        for row, candidate in enumerate(result.lidars):
            use_item = QTableWidgetItem()
            use_item.setFlags(use_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            use_item.setCheckState(
                Qt.CheckState.Checked if row == 0 else Qt.CheckState.Unchecked
            )
            self.lidar_table.setItem(row, 0, use_item)
            name = QTableWidgetItem(
                f"{candidate.display_name} · {candidate.format.upper()} · {candidate.sample_count} frames"
            )
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setData(Qt.ItemDataRole.UserRole, candidate.key)
            self.lidar_table.setItem(row, 1, name)
            self.lidar_table.setItem(row, 2, QTableWidgetItem(candidate.suggested_id))
            self.lidar_table.setItem(
                row,
                3,
                QTableWidgetItem(f"lidar:{candidate.suggested_id}"),
            )
            columns_item = QTableWidgetItem(
                ",".join(candidate.declared_point_columns)
            )
            if candidate.metadata_relative_path is not None:
                columns_item.setToolTip(
                    f"명시적 metadata에서 읽음: {candidate.metadata_relative_path}"
                )
            self.lidar_table.setItem(row, 4, columns_item)
            timestamp_combo = QComboBox()
            timestamp_combo.addItem("사용 안 함", None)
            for timestamp_name in timestamp_names:
                timestamp_combo.addItem(timestamp_name, timestamp_name)
            timestamp_combo.currentIndexChanged.connect(self._configuration_changed)
            self.lidar_table.setCellWidget(row, 5, timestamp_combo)
        self.camera_combo.clear()
        self.camera_combo.addItem("카메라 없음", None)
        for candidate in result.cameras:
            self.camera_combo.addItem(
                f"{candidate.display_name} · {candidate.sample_count} images",
                candidate.key,
            )
        self.camera_timestamp_combo.clear()
        self.camera_timestamp_combo.addItem("사용 안 함", None)
        for timestamp_name in timestamp_names:
            self.camera_timestamp_combo.addItem(timestamp_name, timestamp_name)
        self.camera_timestamp_combo.currentIndexChanged.connect(
            self._configuration_changed
        )
        self._apply_timestamp_column_suggestions(result)
        self._update_camera_fields()
        self._update_sync_fields()

    def _apply_timestamp_column_suggestions(
        self,
        result: DatasetDiscoveryResult,
    ) -> None:
        usable = [
            set(item.columns)
            for item in result.timestamps
            if not item.read_error and item.columns
        ]
        if not usable:
            return
        common = set.intersection(*usable)
        if "sample_id" in common:
            self.sample_column_edit.setText("sample_id")
        for column, clock_domain in (
            ("bag_time_ns", "bag"),
            ("timestamp_ns", "unspecified"),
            ("header_time_ns", "header"),
        ):
            if column in common:
                self.value_column_edit.setText(column)
                self.unit_combo.setCurrentText("ns")
                self.clock_domain_edit.setText(clock_domain)
                break

    def build_request(self) -> DatasetSetupRequest:
        if self.discovery is None:
            raise ValueError("dataset discovery has not completed")
        candidates = {candidate.key: candidate for candidate in self.discovery.lidars}
        method = str(self.sync_method_combo.currentData())
        lidar_setups: list[LidarSetup] = []
        for row in range(self.lidar_table.rowCount()):
            use_item = self.lidar_table.item(row, 0)
            if use_item is None or use_item.checkState() != Qt.CheckState.Checked:
                continue
            key_item = self.lidar_table.item(row, 1)
            sensor_item = self.lidar_table.item(row, 2)
            frame_item = self.lidar_table.item(row, 3)
            columns_item = self.lidar_table.item(row, 4)
            if any(
                item is None
                for item in (key_item, sensor_item, frame_item, columns_item)
            ):
                raise ValueError("LiDAR 설정 표가 완전하지 않습니다.")
            assert key_item is not None
            assert sensor_item is not None
            assert frame_item is not None
            assert columns_item is not None
            candidate = candidates[str(key_item.data(Qt.ItemDataRole.UserRole))]
            sensor_id = sensor_item.text().strip()
            timestamp_combo = self.lidar_table.cellWidget(row, 5)
            timestamp_path = (
                timestamp_combo.currentData()
                if isinstance(timestamp_combo, QComboBox)
                else None
            )
            timestamp = self._timestamp_setup(timestamp_path)
            columns = tuple(
                value.strip() for value in columns_item.text().split(",") if value.strip()
            )
            lidar_setups.append(
                LidarSetup(
                    candidate=candidate,
                    sensor_id=sensor_id,
                    display_name=candidate.display_name,
                    coordinate_frame=frame_item.text().strip(),
                    point_columns=columns,
                    profile_id=f"{sensor_id}_profile",
                    profile_display_name=f"{candidate.display_name} 라벨링",
                    sync_method=method,  # type: ignore[arg-type]
                    tolerance_ns=(
                        round(self.tolerance_spin.value() * 1_000_000)
                        if method == "timestamp_nearest"
                        else None
                    ),
                    timestamp=timestamp,
                )
            )
        camera = self._camera_setup()
        return DatasetSetupRequest(
            source_root=self.source_root,
            config_root=Path(self.config_root_edit.text().strip()),
            display_name=self.display_name_edit.text().strip(),
            dataset_id=self.dataset_id_edit.text().strip(),
            lidars=tuple(lidar_setups),
            camera=camera,
            taxonomy=taxonomy_from_config(self.config),
            coordinate_system_confirmed=self.coordinate_confirm.isChecked(),
            default_profile_id=(lidar_setups[0].profile_id if lidar_setups else None),
        )

    def _camera_setup(self) -> CameraSetup | None:
        if self.discovery is None:
            return None
        key = self.camera_combo.currentData()
        if key is None:
            return None
        candidate = next(item for item in self.discovery.cameras if item.key == key)
        return CameraSetup(
            candidate=candidate,
            sensor_id=self.camera_id_edit.text().strip(),
            display_name=candidate.display_name,
            coordinate_frame=self.camera_frame_edit.text().strip(),
            timestamp=self._timestamp_setup(self.camera_timestamp_combo.currentData()),
        )

    def _timestamp_setup(self, path: object) -> TimestampSetup | None:
        if path is None:
            return None
        return TimestampSetup(
            relative_path=str(path),
            sample_id_column=self.sample_column_edit.text().strip(),
            value_column=self.value_column_edit.text().strip(),
            unit=self.unit_combo.currentText(),  # type: ignore[arg-type]
            clock_domain=self.clock_domain_edit.text().strip(),
        )

    def _start_analysis(self) -> None:
        try:
            request = self.build_request()
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "구성 확인 필요", str(exc))
            return
        self.analysis = None
        self.create_button.setEnabled(False)
        self._cancel.clear()
        self._set_busy(True)
        request_generation = self._configuration_generation
        future = self._executor.submit(
            analyze_generic_dataset,
            request,
            progress=self._emit_setup_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(
            lambda completed: self._finish_future(
                "analysis",
                completed,
                request_generation,
            )
        )

    def _start_setup(self) -> None:
        if self.analysis is None:
            QMessageBox.warning(
                self,
                "구성 분석 필요",
                "현재 설정을 먼저 분석하고 결과를 확인해 주세요.",
            )
            return
        try:
            request = replace(
                self.build_request(),
                dataset_id=self.analysis.dataset_id,
                expected_source_inventory_sha256=(
                    self.analysis.source_inventory_sha256
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, "구성 확인 필요", str(exc))
            return
        self._cancel.clear()
        self._set_busy(True)
        future = self._executor.submit(
            create_generic_dataset,
            request,
            progress=self._emit_setup_progress,
            cancel_check=self._cancel.is_set,
        )
        future.add_done_callback(
            lambda completed: self._finish_future("setup", completed)
        )

    def _emit_setup_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self._bridge.progress.emit(phase, current, total, message)

    def _on_analysis_completed(self, result_object: object) -> None:
        if not isinstance(result_object, DatasetSetupAnalysis):
            self._on_failed("analysis", "unexpected setup analysis result")
            return
        self.analysis = result_object
        self.dataset_id_edit.setText(result_object.dataset_id)
        self._set_busy(False)
        summaries = []
        for profile_id, qa in result_object.sync_qa:
            delta = (
                "-"
                if qa.max_abs_delta_ns is None
                else f"{qa.max_abs_delta_ns / 1_000_000:.3f} ms"
            )
            summaries.append(
                f"{profile_id}: LiDAR {qa.lidar_frame_count}, "
                f"camera matched {qa.matched_camera_count}, "
                f"unmatched {qa.unmatched_camera_count}, "
                f"reuse {qa.camera_sample_reuse_count}, max delta {delta}"
            )
        self.status_label.setText(
            "분석 완료 · 원본 파일 "
            f"{result_object.source_file_count}개 · 생성 전 확인:\n"
            + "\n".join(summaries)
        )

    def _on_analysis_discarded(self) -> None:
        self.analysis = None
        self._set_busy(False)
        self.status_label.setText(
            "분석 중 설정이 변경되어 이전 결과를 폐기했습니다. 다시 분석해 주세요."
        )

    def _on_setup_completed(self, result_object: object) -> None:
        if not isinstance(result_object, DatasetSetupResult):
            self._on_failed("setup", "unexpected setup result")
            return
        self.setup_result = result_object
        self.selected_config_root = result_object.config_root
        self.selected_profile_id = result_object.manifest.default_profile_id
        self._set_busy(False)
        self.status_label.setText(
            f"구성 완료 · {len(result_object.manifest.profiles)} profile · "
            f"{result_object.config_root}"
        )
        self.accept()

    def _on_failed(self, operation: str, message: str) -> None:
        self._set_busy(False)
        if self._cancel.is_set():
            self.status_label.setText("작업을 취소했습니다. 기존 파일은 유지됩니다.")
            return
        self.status_label.setText(f"{operation} 실패: {message}")
        QMessageBox.critical(
            self,
            "데이터셋 구성 실패",
            f"{message}\n\n원본과 기존 dataset.json은 변경되지 않았습니다.",
        )

    def _on_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{phase} · {current}/{total} · {message}")

    def _update_camera_fields(self) -> None:
        enabled = self.camera_combo.currentData() is not None
        for widget in (
            self.camera_id_edit,
            self.camera_frame_edit,
            self.camera_timestamp_combo,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.sync_method_combo.setCurrentIndex(0)
        elif self.sync_method_combo.currentData() == "lidar_only":
            self.sync_method_combo.setCurrentIndex(1)
        self._update_sync_fields()

    def _update_sync_fields(self) -> None:
        method = self.sync_method_combo.currentData()
        has_camera = self.camera_combo.currentData() is not None
        if not has_camera and method != "lidar_only":
            self.sync_method_combo.setCurrentIndex(0)
            method = "lidar_only"
        timestamp_mode = method == "timestamp_nearest"
        for field_widget in (
            self.sample_column_edit,
            self.value_column_edit,
            self.unit_combo,
            self.clock_domain_edit,
            self.tolerance_spin,
            self.camera_timestamp_combo,
        ):
            field_widget.setEnabled(timestamp_mode and has_camera)
        for row in range(self.lidar_table.rowCount()):
            cell_widget = self.lidar_table.cellWidget(row, 5)
            if cell_widget is not None:
                cell_widget.setEnabled(timestamp_mode)
        self._configuration_changed()

    def _configuration_changed(self, *_args: object) -> None:
        self._configuration_generation += 1
        if self.analysis is not None:
            self.analysis = None
            self.status_label.setText(
                "설정이 변경되었습니다. 생성 전에 다시 분석해 주세요."
            )
        if hasattr(self, "create_button"):
            self.create_button.setEnabled(False)
        self._update_apply_enabled()

    def _update_apply_enabled(self) -> None:
        has_lidar = False
        point_columns_ready = True
        timestamp_ready = True
        for row in range(self.lidar_table.rowCount()):
            use_item = self.lidar_table.item(row, 0)
            if use_item is None or use_item.checkState() != Qt.CheckState.Checked:
                continue
            has_lidar = True
            columns_item = self.lidar_table.item(row, 4)
            columns = {
                value.strip()
                for value in (columns_item.text() if columns_item is not None else "").split(",")
                if value.strip()
            }
            point_columns_ready = point_columns_ready and {"x", "y", "z"}.issubset(columns)
            if self.sync_method_combo.currentData() == "timestamp_nearest":
                timestamp_widget = self.lidar_table.cellWidget(row, 5)
                timestamp_ready = timestamp_ready and isinstance(
                    timestamp_widget, QComboBox
                ) and timestamp_widget.currentData() is not None
        if self.sync_method_combo.currentData() == "timestamp_nearest":
            timestamp_ready = (
                timestamp_ready
                and self.camera_combo.currentData() is not None
                and self.camera_timestamp_combo.currentData() is not None
                and bool(self.sample_column_edit.text().strip())
                and bool(self.value_column_edit.text().strip())
                and bool(self.clock_domain_edit.text().strip())
            )
        configuration_ready = (
            self.discovery is not None
            and bool(self.discovery.lidars)
            and has_lidar
            and point_columns_ready
            and timestamp_ready
            and self.coordinate_confirm.isChecked()
        )
        self.apply_button.setEnabled(configuration_ready and not self._busy)
        self.create_button.setEnabled(
            configuration_ready and self.analysis is not None and not self._busy
        )

    def _browse_config_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "구성 및 라벨 저장 폴더 선택",
            self.config_root_edit.text(),
        )
        if selected:
            self.config_root_edit.setText(selected)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.display_name_edit,
            self.config_root_edit,
            self.config_browse_button,
            self.lidar_table,
            self.camera_combo,
            self.camera_id_edit,
            self.camera_frame_edit,
            self.camera_timestamp_combo,
            self.sync_method_combo,
            self.sample_column_edit,
            self.value_column_edit,
            self.unit_combo,
            self.clock_domain_edit,
            self.tolerance_spin,
            self.coordinate_confirm,
        ):
            widget.setEnabled(not busy)
        if not busy:
            has_camera = self.camera_combo.currentData() is not None
            timestamp_mode = (
                has_camera
                and self.sync_method_combo.currentData() == "timestamp_nearest"
            )
            for widget in (
                self.camera_id_edit,
                self.camera_frame_edit,
            ):
                widget.setEnabled(has_camera)
            for widget in (
                self.camera_timestamp_combo,
                self.sample_column_edit,
                self.value_column_edit,
                self.unit_combo,
                self.clock_domain_edit,
                self.tolerance_spin,
            ):
                widget.setEnabled(timestamp_mode)
            for row in range(self.lidar_table.rowCount()):
                cell_widget = self.lidar_table.cellWidget(row, 5)
                if cell_widget is not None:
                    cell_widget.setEnabled(
                        self.sync_method_combo.currentData()
                        == "timestamp_nearest"
                    )
        self._update_apply_enabled()
        self.progress_bar.setRange(0, 0 if busy else 1)

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
