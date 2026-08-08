from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QImageReader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.app.config import load_config
from lidar_label_tool.calibration.waymo_camera import (
    CameraCalibration,
    ProjectedWireframe,
    project_box_wireframe,
)
from lidar_label_tool.calibration_editor import (
    CalibrationDraft,
    CalibrationReferenceBoxes,
    CalibrationSource,
    CameraIntrinsics,
    PoseDelta,
    ProjectionStats,
    build_calibration_document,
    default_adjusted_path,
    load_calibration_file,
    load_calibration_source,
    project_reference_points,
    sample_reference_points,
    save_calibration_document,
)
from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.ui.render_cache import PointCloudRenderCache
from lidar_label_tool.ui.views import BevView, CameraImageView, PointCloud3DView
from lidar_label_tool.workers.frame_loader import FrameLoadPayload, load_frame_payload


class _LoadBridge(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str, str)


class CalibrationEditorWindow(QMainWindow):
    """Read-only dataset viewer with a separate, non-destructive calibration draft."""

    def __init__(
        self,
        dataset_root: Path,
        config_path: Path,
        *,
        profile_id: str | None = None,
        calibration_path: Path | None = None,
        output_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.dataset_root = Path(dataset_root).resolve()
        self.config = load_config(config_path)
        self.adapter = open_dataset_adapter(self.dataset_root, profile_id=profile_id)
        self.index = self.adapter.scan()
        if not self.index.frame_ids:
            raise ValueError("calibration editor requires at least one frame")
        if not self.index.camera_ids:
            raise ValueError("calibration editor requires at least one camera")
        self.importer = WaymoLabelImporter(
            self.config["source_class_mappings"],
            source_format=self._source_format(),
        )
        self.repository = open_label_repository(self.adapter)
        self.calibration_source = (
            load_calibration_file(calibration_path)
            if calibration_path is not None
            else load_calibration_source(self.adapter, self.index)
        )
        self._validate_source_reference(self.calibration_source)
        self.original_source_path = self.calibration_source.source_path
        self.output_path = Path(output_path).resolve() if output_path is not None else None

        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="calibration-load")
        self.bridge = _LoadBridge(self)
        self.bridge.completed.connect(self._accept_frame)
        self.bridge.failed.connect(self._show_load_error)
        self.request_generation = 0
        self.payload: FrameLoadPayload | None = None
        self.drafts: dict[str, CalibrationDraft] = {}
        self.saved_signatures: dict[str, tuple[object, ...]] = {}
        self.verified_frames: dict[str, set[str]] = {}
        self.last_projection: dict[str, dict[str, Any]] = {}
        self.reference_boxes = CalibrationReferenceBoxes()
        self.selected_reference_box_id: str | None = None
        self._sample_cache: dict[tuple[str, int], np.ndarray[Any, np.dtype[np.float32]]] = {}
        self._updating_controls = False
        self._updating_reference_controls = False
        self._updating_view_ratio = False
        self._rendered_point_count = 0
        self._closing = False

        self.render_cache = PointCloudRenderCache(
            max_cache_mb=int(self.config["performance"]["max_cache_mb"])
        )
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(35)
        self.preview_timer.timeout.connect(self._render_preview)

        self.base_window_title = f"Calibration Editor — {self.index.dataset_id}"
        self.setWindowTitle(self.base_window_title)
        self.resize(1680, 1000)
        self._build_ui()
        self._populate_index()
        self._request_frame(self.index.frame_ids[0])

    def _source_format(self) -> str:
        if isinstance(self.adapter, DeviceCentricV2Adapter):
            return "device_centric_v2"
        if isinstance(self.adapter, DeviceCentricAdapter):
            return "device_centric_json"
        return "waymo_frame_json"

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        navigation = QHBoxLayout()
        navigation.addWidget(QLabel("프레임"))
        self.previous_button = QPushButton("이전")
        self.next_button = QPushButton("다음")
        self.frame_combo = QComboBox()
        self.frame_combo.setMinimumWidth(180)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.frame_combo, 1)
        navigation.addWidget(self.next_button)
        navigation.addSpacing(18)
        navigation.addWidget(QLabel("카메라"))
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(180)
        navigation.addWidget(self.camera_combo)
        navigation.addSpacing(18)
        navigation.addWidget(QLabel("카메라 / LiDAR"))
        self.view_ratio_slider = QSlider(Qt.Orientation.Horizontal)
        self.view_ratio_slider.setRange(10, 90)
        self.view_ratio_slider.setValue(65)
        self.view_ratio_slider.setFixedWidth(140)
        self.view_ratio_slider.setToolTip(
            "위 카메라와 아래 LiDAR 영역의 높이 비율입니다. 분할선도 직접 드래그할 수 있습니다."
        )
        self.view_ratio_label = QLabel("65 : 35")
        self.view_ratio_label.setMinimumWidth(48)
        navigation.addWidget(self.view_ratio_slider)
        navigation.addWidget(self.view_ratio_label)
        root_layout.addLayout(navigation)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.view_splitter = QSplitter(Qt.Orientation.Vertical)

        image_container = QWidget()
        image_layout = QVBoxLayout(image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_view = CameraImageView()
        self.preview_status = QLabel("프레임을 불러오는 중…")
        self.preview_status.setWordWrap(True)
        image_layout.addWidget(self.image_view, 1)
        image_layout.addWidget(self.preview_status)
        self.view_splitter.addWidget(image_container)

        cloud_container = QWidget()
        cloud_layout = QVBoxLayout(cloud_container)
        cloud_layout.setContentsMargins(0, 0, 0, 0)

        lidar_splitter = QSplitter(Qt.Orientation.Horizontal)
        point_container = QWidget()
        point_layout = QVBoxLayout(point_container)
        point_layout.setContentsMargins(0, 0, 0, 0)
        point_layout.addWidget(QLabel("3D LiDAR"))
        self.point_view = PointCloud3DView(self.render_cache)
        point_layout.addWidget(self.point_view, 1)

        bev_container = QWidget()
        bev_layout = QVBoxLayout(bev_container)
        bev_layout.setContentsMargins(0, 0, 0, 0)
        bev_layout.addWidget(QLabel("BEV · 기준 박스 생성/이동/크기/yaw 편집"))
        self.bev_view = BevView(self.render_cache)
        bev_layout.addWidget(self.bev_view, 1)

        lidar_splitter.addWidget(point_container)
        lidar_splitter.addWidget(bev_container)
        lidar_splitter.setSizes([620, 620])
        self.cloud_status = QLabel()
        self.cloud_status.setWordWrap(True)
        cloud_layout.addWidget(lidar_splitter, 1)
        cloud_layout.addWidget(self.cloud_status)
        self.view_splitter.addWidget(cloud_container)
        self.view_splitter.setSizes([650, 350])
        main_splitter.addWidget(self.view_splitter)

        control_scroll = QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setMinimumWidth(370)
        control_scroll.setMaximumWidth(470)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self._source_group())
        controls_layout.addWidget(self._overlay_group())
        controls_layout.addWidget(self._reference_box_group())
        controls_layout.addWidget(self._pose_group())
        controls_layout.addWidget(self._intrinsic_group())
        controls_layout.addWidget(self._matrix_group())
        controls_layout.addStretch(1)
        control_scroll.setWidget(controls)
        main_splitter.addWidget(control_scroll)
        main_splitter.setSizes([1260, 420])
        root_layout.addWidget(main_splitter, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Calibration 데이터는 라벨과 별도 상태로 관리됩니다.")

        self.previous_button.clicked.connect(lambda: self._move_frame(-1))
        self.next_button.clicked.connect(lambda: self._move_frame(1))
        self.frame_combo.currentTextChanged.connect(self._request_frame)
        self.camera_combo.currentTextChanged.connect(self._camera_changed)
        self.view_ratio_slider.valueChanged.connect(self._set_view_ratio)
        self.view_splitter.splitterMoved.connect(self._sync_view_ratio_from_splitter)
        self.point_view.objectSelected.connect(self._select_reference_box)
        self.bev_view.objectSelected.connect(self._select_reference_box)
        self.bev_view.createBoxRequested.connect(self._create_reference_box_at)
        self.bev_view.createBoxDragged.connect(self._create_reference_box_from_drag)
        self.bev_view.boxMoved.connect(self._move_reference_box)
        self.bev_view.boxResized.connect(self._resize_reference_box)
        self.bev_view.boxRotated.connect(self._rotate_reference_box)

    def _source_group(self) -> QGroupBox:
        group = QGroupBox("Calibration 작업")
        layout = QVBoxLayout(group)
        self.source_info = QLabel()
        self.source_info.setWordWrap(True)
        self.verified_status = QLabel("검증 프레임: 0개")
        self.verify_button = QPushButton("현재 프레임을 검증 완료로 기록")
        self.load_calibration_button = QPushButton("기존 Calibration JSON 불러오기…")
        self.save_button = QPushButton("조정본 Save As…")
        self.save_button.setStyleSheet("font-weight:600; padding:7px;")
        layout.addWidget(self.source_info)
        layout.addWidget(self.verified_status)
        layout.addWidget(self.verify_button)
        layout.addWidget(self.load_calibration_button)
        layout.addWidget(self.save_button)
        self.verify_button.clicked.connect(self._mark_verified)
        self.load_calibration_button.clicked.connect(self._choose_calibration_file)
        self.save_button.clicked.connect(self._save_as)
        return group

    def _overlay_group(self) -> QGroupBox:
        group = QGroupBox("카메라 미리보기 레이어")
        layout = QVBoxLayout(group)
        self.show_camera_image = QCheckBox(
            "카메라 원본 이미지 표시 (OFF: 검정 배경)"
        )
        self.show_camera_image.setChecked(True)
        self.show_points = QCheckBox("조정 후 LiDAR 포인트 (청록)")
        self.show_points.setChecked(True)
        self.show_boxes = QCheckBox("조정 후 3D/기준 박스 (초록)")
        self.show_boxes.setChecked(True)
        self.show_before = QCheckBox("조정 전 결과 비교 (분홍 점선)")
        self.show_before.setChecked(True)
        self.show_camera_labels = QCheckBox("기존 카메라 2D 박스 (주황)")
        self.show_camera_labels.setChecked(True)
        for check in (
            self.show_camera_image,
            self.show_points,
            self.show_boxes,
            self.show_before,
            self.show_camera_labels,
        ):
            layout.addWidget(check)
            check.toggled.connect(self._schedule_preview)

        form = QFormLayout()
        self.max_projection_points = QSpinBox()
        self.max_projection_points.setRange(1_000, 100_000)
        self.max_projection_points.setSingleStep(5_000)
        self.max_projection_points.setValue(25_000)
        self.max_projection_points.setToolTip(
            "카메라 이미지 위에 그릴 LiDAR point의 최대 개수입니다."
        )
        self.point_size = QDoubleSpinBox()
        self.point_size.setRange(1.0, 30.0)
        self.point_size.setDecimals(0)
        self.point_size.setValue(4.0)
        self.point_size.setSingleStep(1.0)
        self.point_size.setSuffix(" px")
        self.point_size.setToolTip(
            "카메라에 투영되는 LiDAR point의 지름입니다. 원본 point에는 영향이 없습니다."
        )
        self.point_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.point_size_slider.setRange(1, 30)
        self.point_size_slider.setValue(4)
        self.point_size_slider.setToolTip(self.point_size.toolTip())
        point_size_control = QWidget()
        point_size_layout = QHBoxLayout(point_size_control)
        point_size_layout.setContentsMargins(0, 0, 0, 0)
        point_size_layout.addWidget(self.point_size_slider, 1)
        point_size_layout.addWidget(self.point_size)
        form.addRow("투영 포인트 수", self.max_projection_points)
        form.addRow("투영 점 크기", point_size_control)
        layout.addLayout(form)
        self.point_outline = QCheckBox("투영 점 검은 외곽선 (밝은 배경용)")
        self.point_outline.setChecked(False)
        self.point_outline.setToolTip(
            "점이 촘촘한 장면에서는 검은 선처럼 이어질 수 있어 기본값은 OFF입니다."
        )
        layout.addWidget(self.point_outline)
        self.max_projection_points.valueChanged.connect(self._resample_and_preview)
        self.point_size_slider.valueChanged.connect(self.point_size.setValue)
        self.point_size.valueChanged.connect(self._projection_point_size_changed)
        self.point_outline.toggled.connect(self._schedule_preview)
        return group

    def _projection_point_size_changed(self, value: float) -> None:
        slider_value = round(value)
        if self.point_size_slider.value() != slider_value:
            self.point_size_slider.setValue(slider_value)
        self._schedule_preview()

    def _reference_box_group(self) -> QGroupBox:
        group = QGroupBox("LiDAR 기준 박스 · calibration 전용")
        layout = QVBoxLayout(group)
        note = QLabel(
            "BEV에서 점군을 감싸도록 클릭하거나 드래그하세요. 선택한 기준 박스를 "
            "이동·크기 조절·회전하면 카메라 투영이 즉시 갱신됩니다. 이 박스는 현재 "
            "세션에서만 사용하며 원본/작업 라벨과 calibration JSON에 저장하지 않습니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.show_source_boxes = QCheckBox("기존 3D 라벨도 함께 표시·투영 (읽기 전용)")
        self.show_source_boxes.setChecked(True)
        layout.addWidget(self.show_source_boxes)

        template_form = QFormLayout()
        self.reference_class_combo = QComboBox()
        for class_config in self.config["classes"]:
            raw_size = class_config.get("default_size", (4.2, 1.8, 1.6))
            size = tuple(float(value) for value in raw_size)
            if len(size) != 3:
                size = (4.2, 1.8, 1.6)
            self.reference_class_combo.addItem(str(class_config["name"]), size)
        template_form.addRow("새 박스 템플릿", self.reference_class_combo)
        layout.addLayout(template_form)

        self.reference_create_button = QPushButton(
            "새 기준 박스 · BEV에서 위치 클릭/드래그"
        )
        self.reference_create_button.setCheckable(True)
        layout.addWidget(self.reference_create_button)

        self.reference_selection_status = QLabel("선택된 기준 박스 없음")
        self.reference_selection_status.setWordWrap(True)
        layout.addWidget(self.reference_selection_status)

        form = QFormLayout()
        self.reference_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (("x", "x"), ("y", "y"), ("z", "z")):
            spin = self._double_spin(-10_000.0, 10_000.0, 3, 0.05, " m")
            self.reference_spins[key] = spin
            form.addRow(label, spin)
        for key, label in (
            ("length", "length"),
            ("width", "width"),
            ("height", "height"),
        ):
            spin = self._double_spin(0.05, 1_000.0, 3, 0.05, " m")
            self.reference_spins[key] = spin
            form.addRow(label, spin)
        yaw_spin = self._double_spin(-180.0, 180.0, 2, 1.0, "°")
        self.reference_spins["yaw_deg"] = yaw_spin
        form.addRow("yaw", yaw_spin)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.reference_fit_button = QPushButton("포인트 바닥에 맞춤")
        self.reference_delete_button = QPushButton("선택 삭제")
        buttons.addWidget(self.reference_fit_button)
        buttons.addWidget(self.reference_delete_button)
        layout.addLayout(buttons)
        self.reference_clear_button = QPushButton("현재 frame 기준 박스 모두 지우기")
        layout.addWidget(self.reference_clear_button)

        self.reference_create_button.toggled.connect(self._toggle_reference_create_mode)
        self.show_source_boxes.toggled.connect(self._reference_visibility_changed)
        for spin in self.reference_spins.values():
            spin.valueChanged.connect(self._reference_controls_changed)
            spin.setEnabled(False)
        self.reference_fit_button.clicked.connect(self._fit_reference_box_to_points)
        self.reference_delete_button.clicked.connect(self._delete_reference_box)
        self.reference_clear_button.clicked.connect(self._clear_reference_boxes)
        self.reference_fit_button.setEnabled(False)
        self.reference_delete_button.setEnabled(False)
        self.reference_clear_button.setEnabled(False)
        return group

    def _set_view_ratio(self, camera_percent: int) -> None:
        camera_percent = max(
            self.view_ratio_slider.minimum(),
            min(self.view_ratio_slider.maximum(), int(camera_percent)),
        )
        self.view_ratio_label.setText(f"{camera_percent} : {100 - camera_percent}")
        if self._updating_view_ratio:
            return
        sizes = self.view_splitter.sizes()
        total = sum(sizes)
        if total <= 1:
            total = max(1_000, self.view_splitter.height())
        camera_size = max(1, round(total * camera_percent / 100.0))
        self._updating_view_ratio = True
        try:
            self.view_splitter.setSizes([camera_size, max(1, total - camera_size)])
        finally:
            self._updating_view_ratio = False

    def _sync_view_ratio_from_splitter(self, *_: Any) -> None:
        if self._updating_view_ratio:
            return
        sizes = self.view_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        camera_percent = max(
            self.view_ratio_slider.minimum(),
            min(
                self.view_ratio_slider.maximum(),
                round(sizes[0] * 100.0 / total),
            ),
        )
        self._updating_view_ratio = True
        try:
            self.view_ratio_slider.blockSignals(True)
            self.view_ratio_slider.setValue(camera_percent)
            self.view_ratio_label.setText(
                f"{camera_percent} : {100 - camera_percent}"
            )
        finally:
            self.view_ratio_slider.blockSignals(False)
            self._updating_view_ratio = False

    def _pose_group(self) -> QGroupBox:
        group = QGroupBox("Extrinsic 보정 · delta @ base")
        layout = QVBoxLayout(group)
        note = QLabel(
            "이동은 m, 회전은 카메라 target 축의 degree입니다. "
            "회전 합성은 Rz(yaw) · Ry(pitch) · Rx(roll) 순서입니다. "
            "미리보기 camera tool frame은 +X 전방, +Y 좌측, +Z 위입니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        step_form = QFormLayout()
        self.translation_step = QDoubleSpinBox()
        self.translation_step.setRange(0.0001, 1.0)
        self.translation_step.setDecimals(4)
        self.translation_step.setValue(0.01)
        self.translation_step.setSuffix(" m")
        self.rotation_step = QDoubleSpinBox()
        self.rotation_step.setRange(0.001, 10.0)
        self.rotation_step.setDecimals(3)
        self.rotation_step.setValue(0.1)
        self.rotation_step.setSuffix("°")
        step_form.addRow("이동 step", self.translation_step)
        step_form.addRow("회전 step", self.rotation_step)
        layout.addLayout(step_form)

        form = QFormLayout()
        self.pose_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (("x_m", "X"), ("y_m", "Y"), ("z_m", "Z")):
            spin = self._double_spin(-100.0, 100.0, 4, 0.01, " m")
            self.pose_spins[key] = spin
            form.addRow(label, spin)
        for key, label in (
            ("roll_deg", "Roll"),
            ("pitch_deg", "Pitch"),
            ("yaw_deg", "Yaw"),
        ):
            spin = self._double_spin(-180.0, 180.0, 4, 0.1, "°")
            self.pose_spins[key] = spin
            form.addRow(label, spin)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        reset_pose = QPushButton("6DoF만 초기화")
        reset_all = QPushButton("전체 초기화")
        buttons.addWidget(reset_pose)
        buttons.addWidget(reset_all)
        layout.addLayout(buttons)

        self.translation_step.valueChanged.connect(self._update_pose_steps)
        self.rotation_step.valueChanged.connect(self._update_pose_steps)
        for spin in self.pose_spins.values():
            spin.valueChanged.connect(self._controls_changed)
        reset_pose.clicked.connect(self._reset_pose)
        reset_all.clicked.connect(self._reset_all)
        return group

    def _intrinsic_group(self) -> QGroupBox:
        group = QGroupBox("Camera intrinsic")
        layout = QFormLayout(group)
        self.intrinsic_spins: dict[str, QDoubleSpinBox] = {}
        for key in ("fx", "fy", "cx", "cy"):
            minimum = 0.001 if key in {"fx", "fy"} else -1_000_000.0
            spin = self._double_spin(minimum, 1_000_000.0, 4, 1.0, " px")
            self.intrinsic_spins[key] = spin
            layout.addRow(key, spin)
            spin.valueChanged.connect(self._controls_changed)
        self.image_width = QSpinBox()
        self.image_height = QSpinBox()
        for size_spin in (self.image_width, self.image_height):
            size_spin.setRange(1, 100_000)
            size_spin.valueChanged.connect(self._controls_changed)
        layout.addRow("image width", self.image_width)
        layout.addRow("image height", self.image_height)

        self.distortion_model = QComboBox()
        self.distortion_model.addItem("없음", "none")
        self.distortion_model.addItem("Brown-Conrady", "brown_conrady")
        self.distortion_model.currentIndexChanged.connect(self._distortion_changed)
        layout.addRow("distortion", self.distortion_model)

        self.distortion_spins: dict[str, QDoubleSpinBox] = {}
        for key in ("k1", "k2", "p1", "p2", "k3"):
            spin = self._double_spin(-100.0, 100.0, 8, 0.0001)
            self.distortion_spins[key] = spin
            layout.addRow(key, spin)
            spin.valueChanged.connect(self._controls_changed)
        return group

    def _matrix_group(self) -> QGroupBox:
        group = QGroupBox("현재 T_camera_reference")
        layout = QVBoxLayout(group)
        self.matrix_text = QPlainTextEdit()
        self.matrix_text.setReadOnly(True)
        self.matrix_text.setMaximumHeight(125)
        self.matrix_text.setStyleSheet("font-family:Consolas,monospace;")
        layout.addWidget(self.matrix_text)
        return group

    @staticmethod
    def _double_spin(
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
        suffix: str = "",
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        return spin

    def _populate_index(self) -> None:
        self.frame_combo.blockSignals(True)
        self.camera_combo.blockSignals(True)
        self.frame_combo.addItems(self.index.frame_ids)
        self.camera_combo.addItems(self.index.camera_ids)
        self.frame_combo.blockSignals(False)
        self.camera_combo.blockSignals(False)
        self._refresh_source_info()

    def _refresh_source_info(self) -> None:
        profile = f" · profile {self.index.profile_id}" if self.index.profile_id else ""
        source = (
            str(self.calibration_source.source_path)
            if self.calibration_source.source_path is not None
            else "없음 — identity extrinsic과 추정 intrinsic으로 시작"
        )
        self.source_info.setText(
            f"Dataset: {self.index.dataset_id}{profile}\n"
            f"Reference: {self.index.reference_frame}\n"
            f"기준 calibration: {source}\n"
            "원본은 덮어쓰지 않으며 저장 후 자동 활성화하지 않습니다."
        )

    def _validate_source_reference(self, source: CalibrationSource) -> None:
        document = source.document
        if not isinstance(document, Mapping):
            return
        reference = str(document.get("reference_frame", ""))
        if reference != self.index.reference_frame:
            raise ValueError(
                "calibration reference_frame does not match the active dataset: "
                f"{reference!r} != {self.index.reference_frame!r}"
            )

    def _request_frame(self, frame_id: str) -> None:
        if not frame_id or self._closing:
            return
        self.request_generation += 1
        request = self.request_generation
        self.selected_reference_box_id = None
        self.reference_create_button.setChecked(False)
        self.reference_create_button.setEnabled(False)
        self.point_view.setEnabled(False)
        self.bev_view.setEnabled(False)
        self._load_reference_box_controls()
        self.frame_combo.setEnabled(False)
        self.statusBar().showMessage(f"{frame_id} LiDAR와 카메라를 불러오는 중…")
        future = self.executor.submit(
            load_frame_payload,
            self.adapter,
            self.importer,
            frame_id,
            self.repository,
        )
        def finish(completed: Future[FrameLoadPayload]) -> None:
            self._finish_future(request, frame_id, completed)

        future.add_done_callback(finish)

    def _finish_future(
        self,
        request: int,
        frame_id: str,
        future: Future[FrameLoadPayload],
    ) -> None:
        if self._closing:
            return
        try:
            payload = future.result()
        except Exception as exc:
            self.bridge.failed.emit(request, frame_id, f"{type(exc).__name__}: {exc}")
        else:
            self.bridge.completed.emit(request, payload)

    def _accept_frame(self, request: int, payload_object: object) -> None:
        if request != self.request_generation or not isinstance(
            payload_object, FrameLoadPayload
        ):
            return
        self.payload = payload_object
        self.selected_reference_box_id = None
        self.reference_create_button.setChecked(False)
        self.reference_create_button.setEnabled(True)
        self.point_view.setEnabled(True)
        self.bev_view.setEnabled(True)
        self.frame_combo.setEnabled(True)
        clouds = self._active_clouds()
        max_points = int(self.config["point_cloud"]["max_render_points"])
        point_size = float(self.config["views"]["point_size"])
        color_mode = str(self.config["views"]["point_color_mode"])
        uniform_color = str(self.config["views"]["uniform_point_color"])
        self._rendered_point_count = self.point_view.set_clouds(
            clouds,
            max_points=max_points,
            point_size=point_size,
            color_mode=color_mode,
            uniform_color=uniform_color,
        )
        self.bev_view.set_clouds(
            clouds,
            max_points=max_points,
            point_size=point_size,
            color_mode=color_mode,
            uniform_color=uniform_color,
        )
        self._render_lidar_boxes()
        self._ensure_draft()
        self._load_draft_controls()
        self._render_preview()
        self.statusBar().showMessage(f"{payload_object.source.frame_id} 준비됨")

    def _show_load_error(self, request: int, frame_id: str, message: str) -> None:
        if request != self.request_generation:
            return
        self.reference_create_button.setEnabled(True)
        self.point_view.setEnabled(True)
        self.bev_view.setEnabled(True)
        self.frame_combo.setEnabled(True)
        self.statusBar().showMessage(f"{frame_id} 로드 실패")
        QMessageBox.critical(self, "프레임 로드 실패", f"{frame_id}\n\n{message}")

    def _active_clouds(self) -> list[PointCloudData]:
        if self.payload is None:
            return []
        return [
            cloud
            for sensor_clouds in self.payload.clouds.values()
            for cloud in sensor_clouds
        ]

    def _current_frame_id(self) -> str | None:
        return self.payload.source.frame_id if self.payload is not None else None

    def _current_reference_boxes(self) -> tuple[LabeledObject, ...]:
        frame_id = self._current_frame_id()
        return self.reference_boxes.for_frame(frame_id) if frame_id is not None else ()

    def _selected_reference_box(self) -> LabeledObject | None:
        frame_id = self._current_frame_id()
        if frame_id is None:
            return None
        return self.reference_boxes.find(frame_id, self.selected_reference_box_id)

    def _visible_box_objects(self) -> tuple[LabeledObject, ...]:
        source_objects = (
            self.payload.label.objects
            if self.payload is not None and self.show_source_boxes.isChecked()
            else ()
        )
        return source_objects + self._current_reference_boxes()

    def _render_lidar_boxes(self) -> None:
        if self.payload is None:
            return
        objects = self._visible_box_objects()
        self.point_view.set_boxes(
            objects,
            selected_id=self.selected_reference_box_id,
            show_labels=True,
        )
        self.bev_view.set_boxes(
            objects,
            selected_id=self.selected_reference_box_id,
            show_labels=True,
        )
        self._load_reference_box_controls()
        total = sum(cloud.point_count for cloud in self._active_clouds())
        source_count = len(self.payload.label.objects)
        reference_count = len(self._current_reference_boxes())
        source_visibility = "표시" if self.show_source_boxes.isChecked() else "숨김"
        self.cloud_status.setText(
            f"{self.payload.source.frame_id} · 원본 {total:,} points · "
            f"3D/BEV 표시 {self._rendered_point_count:,} · 기존 boxes "
            f"{source_count} ({source_visibility}) · 임시 기준 boxes {reference_count}"
        )

    def _refresh_reference_views(self) -> None:
        self._render_lidar_boxes()
        self._schedule_preview()

    def _reference_visibility_changed(self, *_: Any) -> None:
        self._refresh_reference_views()

    def _toggle_reference_create_mode(self, enabled: bool) -> None:
        self.bev_view.set_create_mode(enabled)
        self.reference_create_button.setText(
            "생성 모드 ON · BEV에서 클릭/드래그 (다시 눌러 취소)"
            if enabled
            else "새 기준 박스 · BEV에서 위치 클릭/드래그"
        )
        if enabled:
            self.statusBar().showMessage(
                "BEV에서 대상 point cloud를 감싸도록 클릭하거나 드래그하세요."
            )

    def _create_reference_box_at(self, x: float, y: float) -> None:
        self._create_reference_box(x, y)

    def _create_reference_box_from_drag(
        self,
        x: float,
        y: float,
        length: float,
        width: float,
    ) -> None:
        self._create_reference_box(x, y, length=length, width=width)

    def _create_reference_box(
        self,
        x: float,
        y: float,
        *,
        length: float | None = None,
        width: float | None = None,
    ) -> None:
        frame_id = self._current_frame_id()
        if frame_id is None:
            return
        raw_size = self.reference_class_combo.currentData()
        default_size = (
            tuple(float(value) for value in raw_size)
            if isinstance(raw_size, (list, tuple)) and len(raw_size) == 3
            else (4.2, 1.8, 1.6)
        )
        box_length = max(0.05, length if length is not None else default_size[0])
        box_width = max(0.05, width if width is not None else default_size[1])
        created = self.reference_boxes.create(
            frame_id,
            class_name=self.reference_class_combo.currentText(),
            x=x,
            y=y,
            length=box_length,
            width=box_width,
            height=default_size[2],
            clouds=self._active_clouds(),
        )
        self.selected_reference_box_id = created.id
        self.reference_create_button.setChecked(False)
        self._refresh_reference_views()
        z_mode = str(created.source.get("z_initialization", ""))
        z_text = "포인트 바닥에 맞춤" if z_mode == "point_floor" else "기본 바닥 z=0"
        self.statusBar().showMessage(
            f"{created.attributes['name']} 생성 · {z_text} · 라벨 파일에는 저장되지 않음"
        )

    def _select_reference_box(self, object_id: object) -> None:
        frame_id = self._current_frame_id()
        target = None if object_id is None else str(object_id)
        selected = (
            self.reference_boxes.find(frame_id, target)
            if frame_id is not None
            else None
        )
        self.selected_reference_box_id = selected.id if selected is not None else None
        if target is not None and selected is None:
            self.statusBar().showMessage(
                "기존 라벨 박스는 calibration 편집기에서 읽기 전용입니다. "
                "별도 기준 박스를 만들어 조정하세요."
            )
        self._refresh_reference_views()

    def _update_reference_box(self, object_id: str, **changes: float) -> None:
        frame_id = self._current_frame_id()
        if frame_id is None:
            return
        current = self.reference_boxes.find(frame_id, object_id)
        if current is None:
            return
        try:
            updated_box = replace(current.box3d, **changes)
        except ValueError as exc:
            self.reference_selection_status.setText(f"박스 값 오류: {exc}")
            return
        self.reference_boxes.replace_box(frame_id, object_id, updated_box)
        self.selected_reference_box_id = object_id
        self._refresh_reference_views()

    def _move_reference_box(self, object_id: str, x: float, y: float) -> None:
        self._update_reference_box(object_id, x=x, y=y)

    def _resize_reference_box(
        self,
        object_id: str,
        x: float,
        y: float,
        length: float,
        width: float,
    ) -> None:
        self._update_reference_box(
            object_id,
            x=x,
            y=y,
            length=length,
            width=width,
        )

    def _rotate_reference_box(self, object_id: str, yaw: float) -> None:
        self._update_reference_box(object_id, yaw=yaw)

    def _load_reference_box_controls(self) -> None:
        selected = self._selected_reference_box()
        enabled = selected is not None
        self._updating_reference_controls = True
        try:
            for spin in self.reference_spins.values():
                spin.setEnabled(enabled)
            self.reference_fit_button.setEnabled(enabled)
            self.reference_delete_button.setEnabled(enabled)
            self.reference_clear_button.setEnabled(bool(self._current_reference_boxes()))
            if selected is None:
                self.reference_selection_status.setText("선택된 기준 박스 없음")
                return
            box = selected.box3d
            for key in ("x", "y", "z", "length", "width", "height"):
                self.reference_spins[key].setValue(float(getattr(box, key)))
            self.reference_spins["yaw_deg"].setValue(float(np.degrees(box.yaw)))
            self.reference_selection_status.setText(
                f"{selected.attributes.get('name', selected.class_name)} · "
                f"{selected.id[-8:]} · 노란색으로 선택됨"
            )
        finally:
            self._updating_reference_controls = False

    def _reference_controls_changed(self, *_: Any) -> None:
        if self._updating_reference_controls:
            return
        frame_id = self._current_frame_id()
        selected = self._selected_reference_box()
        if frame_id is None or selected is None:
            return
        try:
            box = Box3D(
                x=self.reference_spins["x"].value(),
                y=self.reference_spins["y"].value(),
                z=self.reference_spins["z"].value(),
                length=self.reference_spins["length"].value(),
                width=self.reference_spins["width"].value(),
                height=self.reference_spins["height"].value(),
                yaw=float(np.radians(self.reference_spins["yaw_deg"].value())),
            )
        except ValueError as exc:
            self.reference_selection_status.setText(f"박스 값 오류: {exc}")
            return
        self.reference_boxes.replace_box(frame_id, selected.id, box)
        self._refresh_reference_views()

    def _fit_reference_box_to_points(self, *_: Any) -> None:
        frame_id = self._current_frame_id()
        selected = self._selected_reference_box()
        if frame_id is None or selected is None:
            return
        fitted = self.reference_boxes.fit_to_points(
            frame_id,
            selected.id,
            self._active_clouds(),
        )
        if fitted is None:
            self.reference_selection_status.setText(
                "포인트 바닥 맞춤 실패 · 박스 footprint 안쪽 포인트가 부족합니다."
            )
            return
        self._refresh_reference_views()
        self.statusBar().showMessage("선택 기준 박스의 bottom을 포인트 바닥에 맞췄습니다.")

    def _delete_reference_box(self, *_: Any) -> None:
        frame_id = self._current_frame_id()
        selected = self._selected_reference_box()
        if frame_id is None or selected is None:
            return
        self.reference_boxes.delete(frame_id, selected.id)
        self.selected_reference_box_id = None
        self._refresh_reference_views()
        self.statusBar().showMessage("임시 기준 박스를 삭제했습니다.")

    def _clear_reference_boxes(self, *_: Any) -> None:
        frame_id = self._current_frame_id()
        if frame_id is None:
            return
        removed = self.reference_boxes.clear(frame_id)
        self.selected_reference_box_id = None
        self.reference_create_button.setChecked(False)
        self._refresh_reference_views()
        self.statusBar().showMessage(
            f"현재 frame의 임시 기준 박스 {removed}개를 지웠습니다."
        )

    def _current_image_path(self) -> Path | None:
        if self.payload is None:
            return None
        return self.payload.source.image_paths.get(self.camera_combo.currentText())

    def _ensure_draft(self) -> CalibrationDraft | None:
        camera_id = self.camera_combo.currentText()
        if not camera_id:
            return None
        existing = self.drafts.get(camera_id)
        if existing is not None:
            return existing
        image_path = self._current_image_path()
        if image_path is None:
            return None
        size = QImageReader(str(image_path)).size()
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            raise ValueError(f"cannot read camera image size: {image_path}")
        draft = self.calibration_source.draft_for(
            camera_id,
            self.index.reference_frame,
            (size.width(), size.height()),
        )
        self.drafts[camera_id] = draft
        self.saved_signatures[camera_id] = draft.signature()
        self.verified_frames[camera_id] = set()
        return draft

    def _camera_changed(self, _: str) -> None:
        if self.payload is None:
            return
        try:
            self._ensure_draft()
            self._load_draft_controls()
            self._render_preview()
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Calibration 초기화 실패", str(exc))

    def _load_draft_controls(self) -> None:
        camera_id = self.camera_combo.currentText()
        draft = self.drafts.get(camera_id)
        if draft is None:
            return
        self._updating_controls = True
        try:
            correction = draft.correction
            for key, spin in self.pose_spins.items():
                spin.setValue(float(getattr(correction, key)))
            intrinsics = draft.intrinsics
            for key, spin in self.intrinsic_spins.items():
                spin.setValue(float(getattr(intrinsics, key)))
            self.image_width.setValue(intrinsics.width)
            self.image_height.setValue(intrinsics.height)
            model_index = self.distortion_model.findData(intrinsics.distortion_model)
            self.distortion_model.setCurrentIndex(max(0, model_index))
            coefficients = intrinsics.padded_distortion()
            for key, value in zip(("k1", "k2", "p1", "p2", "k3"), coefficients):
                self.distortion_spins[key].setValue(value)
            self._set_distortion_controls_enabled()
        finally:
            self._updating_controls = False
        self._update_matrix(draft)
        self._update_verified_status()
        self._update_dirty_title()

    def _controls_changed(self, *_: Any) -> None:
        if self._updating_controls:
            return
        camera_id = self.camera_combo.currentText()
        draft = self.drafts.get(camera_id)
        if draft is None:
            return
        try:
            correction = PoseDelta(
                **{key: spin.value() for key, spin in self.pose_spins.items()}
            )
            model = str(self.distortion_model.currentData())
            coefficients = (
                tuple(
                    self.distortion_spins[key].value()
                    for key in ("k1", "k2", "p1", "p2", "k3")
                )
                if model != "none"
                else ()
            )
            intrinsics = CameraIntrinsics(
                fx=self.intrinsic_spins["fx"].value(),
                fy=self.intrinsic_spins["fy"].value(),
                cx=self.intrinsic_spins["cx"].value(),
                cy=self.intrinsic_spins["cy"].value(),
                width=self.image_width.value(),
                height=self.image_height.value(),
                distortion_model=model,
                distortion_coefficients=coefficients,
            )
        except ValueError as exc:
            self.preview_status.setText(f"입력값 오류: {exc}")
            return
        updated = draft.with_correction(correction).with_intrinsics(intrinsics)
        self.drafts[camera_id] = updated
        self.verified_frames.setdefault(camera_id, set()).clear()
        self._update_matrix(updated)
        self._update_verified_status()
        self._update_dirty_title()
        self._schedule_preview()

    def _distortion_changed(self, *_: Any) -> None:
        self._set_distortion_controls_enabled()
        self._controls_changed()

    def _set_distortion_controls_enabled(self) -> None:
        enabled = self.distortion_model.currentData() == "brown_conrady"
        for spin in self.distortion_spins.values():
            spin.setEnabled(enabled)

    def _update_pose_steps(self, *_: Any) -> None:
        for key in ("x_m", "y_m", "z_m"):
            self.pose_spins[key].setSingleStep(self.translation_step.value())
        for key in ("roll_deg", "pitch_deg", "yaw_deg"):
            self.pose_spins[key].setSingleStep(self.rotation_step.value())

    def _reset_pose(self) -> None:
        camera_id = self.camera_combo.currentText()
        draft = self.drafts.get(camera_id)
        if draft is None:
            return
        self.drafts[camera_id] = draft.with_correction(PoseDelta())
        self.verified_frames.setdefault(camera_id, set()).clear()
        self._load_draft_controls()
        self._render_preview()

    def _reset_all(self) -> None:
        camera_id = self.camera_combo.currentText()
        draft = self.drafts.get(camera_id)
        if draft is None:
            return
        self.drafts[camera_id] = draft.reset()
        self.verified_frames.setdefault(camera_id, set()).clear()
        self._load_draft_controls()
        self._render_preview()

    def _schedule_preview(self, *_: Any) -> None:
        self.preview_timer.start()

    def _resample_and_preview(self, *_: Any) -> None:
        self._sample_cache.clear()
        self._schedule_preview()

    def _sampled_points(self) -> np.ndarray[Any, np.dtype[np.float32]]:
        if self.payload is None:
            return np.empty((0, 3), dtype=np.float32)
        key = (self.payload.source.frame_id, self.max_projection_points.value())
        cached = self._sample_cache.get(key)
        if cached is None:
            cached = sample_reference_points(
                self._active_clouds(),
                max_points=self.max_projection_points.value(),
                reference_frame=self.index.reference_frame,
            )
            self._sample_cache[key] = cached
        return cached

    def _render_preview(self) -> None:
        if self.payload is None:
            return
        image_path = self._current_image_path()
        camera_id = self.camera_combo.currentText()
        if image_path is None:
            self.image_view.clear_image()
            self.preview_status.setText(f"{camera_id}: 현재 프레임에 카메라 이미지 없음")
            return
        draft = self.drafts.get(camera_id)
        if draft is None:
            self.preview_status.setText(f"{camera_id}: calibration draft 없음")
            return
        try:
            effective_calibration = draft.effective_camera_calibration()
            baseline_calibration = draft.baseline_camera_calibration()
            points = self._sampled_points()
            effective_projection = project_reference_points(points, effective_calibration)
            comparison_projection = (
                project_reference_points(points, baseline_calibration)
                if self.show_before.isChecked() and draft.is_adjusted
                else None
            )
            effective_wireframes = self._project_boxes(effective_calibration)
            comparison_wireframes = (
                self._project_boxes(baseline_calibration)
                if self.show_before.isChecked() and draft.is_adjusted
                else ()
            )
        except (TypeError, ValueError) as exc:
            self.preview_status.setText(f"투영 불가: {exc}")
            return

        camera_labels = (
            self._labels_for_camera(
                self.payload.reference_layers.get("camera"), camera_id
            )
            if self.show_camera_labels.isChecked()
            else ()
        )
        self.image_view.set_image(
            image_path,
            camera_labels,
            (),
            effective_wireframes if self.show_boxes.isChecked() else (),
            selected_object_id=self.selected_reference_box_id,
            camera_id=camera_id,
            box_line_width=2.0,
            projected_points=(
                effective_projection.uv if self.show_points.isChecked() else None
            ),
            comparison_points=(
                comparison_projection.uv
                if comparison_projection is not None and self.show_points.isChecked()
                else None
            ),
            comparison_wireframes=(
                comparison_wireframes if self.show_boxes.isChecked() else ()
            ),
            projected_point_size=self.point_size.value(),
            projected_point_outline=self.point_outline.isChecked(),
            show_camera_image=self.show_camera_image.isChecked(),
            preserve_view=True,
        )
        stats = effective_projection.stats
        delta_text = self._timestamp_delta_text()
        initial_warning = (
            " · intrinsic은 이미지 크기 기반 추정값"
            if draft.source_kind == "new"
            else ""
        )
        size_warning = self._image_size_warning(draft, image_path)
        self.preview_status.setText(
            f"조정 후: sample {stats.sampled_points:,} / 카메라 앞 "
            f"{stats.points_in_front:,} / 이미지 내부 {stats.points_in_image:,}"
            f"{delta_text}{initial_warning}{size_warning}"
        )
        self.last_projection[camera_id] = self._projection_summary(stats)

    def _project_boxes(
        self, calibration: CameraCalibration
    ) -> tuple[ProjectedWireframe, ...]:
        if self.payload is None:
            return ()
        return tuple(
            project_box_wireframe(obj.id, obj.box3d, calibration)
            for obj in self._visible_box_objects()
        )

    def _image_size_warning(self, draft: CalibrationDraft, image_path: Path) -> str:
        size = QImageReader(str(image_path)).size()
        if not size.isValid():
            return ""
        if (draft.intrinsics.width, draft.intrinsics.height) == (
            size.width(),
            size.height(),
        ):
            return ""
        return (
            f" · 경고: calibration image_size {draft.intrinsics.width}×"
            f"{draft.intrinsics.height}, 실제 {size.width()}×{size.height()}"
        )

    def _timestamp_delta_text(self) -> str:
        if self.payload is None:
            return ""
        value = self.payload.source.metadata.get("camera_delta_ns")
        if value is None:
            return ""
        try:
            return f" · Δt {float(value) / 1_000_000.0:+.3f} ms"
        except (TypeError, ValueError):
            return " · Δt 형식 오류"

    @staticmethod
    def _projection_summary(stats: ProjectionStats) -> dict[str, int]:
        return {
            "sampled_points": stats.sampled_points,
            "points_in_front": stats.points_in_front,
            "finite_points": stats.finite_points,
            "points_in_image": stats.points_in_image,
        }

    @staticmethod
    def _labels_for_camera(
        layer: Any, camera_id: str
    ) -> Iterable[Mapping[str, Any]]:
        if not isinstance(layer, list):
            return ()
        for group in layer:
            if isinstance(group, Mapping) and group.get("name") == camera_id:
                labels = group.get("labels", ())
                return labels if isinstance(labels, list) else ()
        return ()

    def _update_matrix(self, draft: CalibrationDraft) -> None:
        matrix = draft.effective_transform
        self.matrix_text.setPlainText(
            "\n".join("  ".join(f"{value: .8f}" for value in row) for row in matrix)
        )

    def _move_frame(self, offset: int) -> None:
        current = self.frame_combo.currentIndex()
        target = max(0, min(self.frame_combo.count() - 1, current + offset))
        if target != current:
            self.frame_combo.setCurrentIndex(target)

    def _mark_verified(self) -> None:
        if self.payload is None:
            return
        camera_id = self.camera_combo.currentText()
        self.verified_frames.setdefault(camera_id, set()).add(
            self.payload.source.frame_id
        )
        self._update_verified_status()
        self.statusBar().showMessage(
            f"{camera_id} · {self.payload.source.frame_id} 검증 프레임으로 기록"
        )

    def _update_verified_status(self) -> None:
        camera_id = self.camera_combo.currentText()
        frames = self.verified_frames.get(camera_id, set())
        preview = ", ".join(sorted(frames)[:4])
        if len(frames) > 4:
            preview += ", …"
        suffix = f" ({preview})" if preview else ""
        self.verified_status.setText(f"검증 프레임: {len(frames)}개{suffix}")

    def _save_as(self) -> None:
        camera_id = self.camera_combo.currentText()
        draft = self.drafts.get(camera_id)
        if draft is None:
            QMessageBox.warning(self, "저장할 수 없음", "활성 calibration draft가 없습니다.")
            return
        suggested = self.output_path or default_adjusted_path(self.index, camera_id)
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "조정한 calibration 저장",
            str(suggested),
            "Calibration JSON (*.json)",
        )
        if not selected:
            return
        target = Path(selected)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        ordered_verified = tuple(
            frame_id
            for frame_id in self.index.frame_ids
            if frame_id in self.verified_frames.get(camera_id, set())
        )
        try:
            document = build_calibration_document(
                self.calibration_source,
                draft,
                self.adapter,
                self.index,
                verified_frame_ids=ordered_verified,
                projection_summary=self.last_projection.get(camera_id),
            )
            fingerprint = save_calibration_document(
                target,
                document,
                source_path=self.original_source_path,
                expected_source_fingerprint=self.calibration_source.source_fingerprint,
            )
            reloaded = CameraCalibration.from_generic(
                camera_id, document["cameras"][camera_id]
            )
            reloaded_transform = np.linalg.inv(reloaded.t_vehicle_camera)
            if not np.allclose(reloaded_transform, draft.effective_transform, atol=1e-9):
                raise ValueError("saved calibration transform reload check failed")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Calibration 저장 실패",
                f"기존 파일은 보존되었습니다.\n\n{type(exc).__name__}: {exc}",
            )
            return
        self.output_path = target.resolve()
        self.calibration_source = replace(
            self.calibration_source,
            document=document,
        )
        self.saved_signatures[camera_id] = draft.signature()
        self._update_dirty_title()
        self.statusBar().showMessage(f"저장 완료: {target}")
        QMessageBox.information(
            self,
            "Calibration 조정본 저장 완료",
            f"저장 경로:\n{target}\n\nSHA-256:\n{fingerprint}\n\n"
            "원본 calibration과 dataset profile은 변경하지 않았습니다. "
            "이 파일을 실제 라벨링에 사용하려면 별도로 활성 calibration으로 채택하세요.",
        )

    def _choose_calibration_file(self) -> None:
        if self._has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "현재 조정값 교체",
                "저장하지 않은 현재 조정값을 버리고 다른 calibration을 불러오시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        initial = (
            self.calibration_source.source_path.parent
            if self.calibration_source.source_path is not None
            else (self.index.configuration_root or self.index.root)
        )
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "기존 calibration JSON 불러오기",
            str(initial),
            "Calibration JSON (*.json)",
        )
        if not selected:
            return
        try:
            source = load_calibration_file(Path(selected))
            self._validate_source_reference(source)
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Calibration을 불러올 수 없음",
                f"{type(exc).__name__}: {exc}",
            )
            return
        self.calibration_source = source
        self.original_source_path = source.source_path
        self.drafts.clear()
        self.saved_signatures.clear()
        self.verified_frames.clear()
        self.last_projection.clear()
        self._refresh_source_info()
        try:
            self._ensure_draft()
            self._load_draft_controls()
            self._render_preview()
        except (KeyError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Calibration 초기화 실패", str(exc))

    def _has_unsaved_changes(self) -> bool:
        return any(
            draft.signature() != self.saved_signatures.get(camera_id)
            for camera_id, draft in self.drafts.items()
        )

    def _update_dirty_title(self) -> None:
        prefix = "*" if self._has_unsaved_changes() else ""
        self.setWindowTitle(prefix + self.base_window_title)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "저장하지 않은 calibration 변경",
                "저장하지 않은 calibration 조정값이 있습니다. 그래도 닫으시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._closing = True
        self.request_generation += 1
        self.preview_timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()
