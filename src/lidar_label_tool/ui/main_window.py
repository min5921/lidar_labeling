from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.app.config import load_config
from lidar_label_tool import __version__
from lidar_label_tool.calibration.waymo_camera import (
    CameraCalibration,
    ProjectedWireframe,
    camera_synced_projection_box,
    project_box_wireframe,
)
from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.labels.json_repository import LabelConflictError, LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.box_propagation import created_objects, merge_carried_objects
from lidar_label_tool.services.recovery import RecoveryStore
from lidar_label_tool.services.session_lock import SessionLock
from lidar_label_tool.ui.panels import CameraPanel, ObjectEditorPanel
from lidar_label_tool.ui.views import (
    BevView,
    CameraImageView,
    ObjectDetail3DView,
    PointCloud3DView,
    SideView,
)
from lidar_label_tool.workers.frame_loader import FrameLoadPayload, load_frame_payload


class _LoadBridge(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str, str)


class MainWindow(QMainWindow):
    def __init__(
        self,
        dataset_root: Path,
        config_path: Path,
        workspace_root: Path | None = None,
        session_lock: SessionLock | None = None,
    ) -> None:
        super().__init__()
        self.dataset_root = Path(dataset_root)
        self.config = load_config(config_path)
        self.adapter = open_dataset_adapter(self.dataset_root)
        self.index = self.adapter.scan()
        self.importer = WaymoLabelImporter(
            self.config["source_class_mappings"],
            source_format=(
                "device_centric_json"
                if isinstance(self.adapter, DeviceCentricAdapter)
                else "waymo_frame_json"
            ),
        )
        self.repository = (
            LabelRepository.for_workspace(workspace_root, self.index.dataset_id)
            if workspace_root is not None
            else LabelRepository.for_sidecar(self.dataset_root, self.index.dataset_id)
        )
        self.workspace_root = workspace_root
        self.session_lock = session_lock
        self.recovery_store = RecoveryStore(self.repository.annotation_dir)
        self._ignored_recovery_frames: set[str] = set()
        self.camera_calibrations: dict[str, CameraCalibration] = {}
        if isinstance(self.adapter, WaymoFrameCentricAdapter):
            for data in self.adapter.segment.get("camera_calibrations", []):
                try:
                    calibration = CameraCalibration.from_waymo(data)
                except (KeyError, TypeError, ValueError):
                    continue
                self.camera_calibrations[calibration.camera_id] = calibration
        elif isinstance(self.adapter, DeviceCentricAdapter):
            for camera_id, data in self.adapter.camera_calibrations.items():
                try:
                    calibration = CameraCalibration.from_generic(camera_id, data)
                except (KeyError, TypeError, ValueError):
                    continue
                self.camera_calibrations[calibration.camera_id] = calibration
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="frame-load")
        self.bridge = _LoadBridge(self)
        self.bridge.completed.connect(self._accept_frame)
        self.bridge.failed.connect(self._show_load_error)
        self.request_generation = 0
        self.payload: FrameLoadPayload | None = None
        self.history: AnnotationHistory | None = None
        self.sensor_checks: dict[str, QCheckBox] = {}
        self.uniform_point_color = str(self.config["views"]["uniform_point_color"])
        self._updating_editor = False
        self._closing = False
        self._pending_carry_target: str | None = None
        self._pending_carried_objects: tuple[LabeledObject, ...] = ()
        self._pending_carried_selection: str | None = None
        self._detail_reset_requested = False

        self.base_window_title = f"LiDAR Label Tool — {self.index.dataset_id}"
        self.setWindowTitle(self.base_window_title)
        self.resize(1600, 980)
        self._build_ui()
        self._populate_index()
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setInterval(
            max(1, int(self.config["editing"]["recovery_interval_s"])) * 1000
        )
        self.recovery_timer.timeout.connect(self._write_recovery_snapshot)
        self.recovery_timer.start()
        self._request_frame(self.index.frame_ids[0])

    def _build_ui(self) -> None:
        self.view_3d = PointCloud3DView()
        self.bev_view = BevView()
        self.image_view = CameraImageView()
        self.detail_view = ObjectDetail3DView()
        self.side_view = SideView()
        self.view_3d.objectSelected.connect(self._select_object_id)
        self.bev_view.objectSelected.connect(self._select_object_id)
        self.bev_view.boxMoved.connect(self._move_box_from_bev)
        self.bev_view.boxResized.connect(self._resize_box_from_bev)
        self.bev_view.boxRotated.connect(self._rotate_box_from_bev)
        self.bev_view.createBoxRequested.connect(self._create_box_at)
        self.bev_view.createBoxDragged.connect(self._create_box_from_drag)
        self.side_view.boxVerticalMoved.connect(self._move_box_vertical_from_side)
        self.side_view.boxHeightResized.connect(self._resize_box_height_from_side)

        right_views = QSplitter(Qt.Orientation.Vertical)
        right_views.addWidget(self._framed("카메라", self.image_view))
        right_views.addWidget(
            self._framed("선택 객체 상세 3D · 박스 중심 / yaw 정렬", self.detail_view)
        )
        right_views.setSizes([520, 440])

        primary_views = QSplitter(Qt.Orientation.Horizontal)
        primary_views.addWidget(self._framed("전체 3D 포인트 클라우드", self.view_3d))
        primary_views.addWidget(right_views)
        primary_views.setSizes([900, 650])

        self.bev_frame = self._framed("BEV 보조 뷰", self.bev_view)
        self.side_frame = self._framed("측면 보조 뷰", self.side_view)
        self.auxiliary_views = QSplitter(Qt.Orientation.Horizontal)
        self.auxiliary_views.addWidget(self.bev_frame)
        self.auxiliary_views.addWidget(self.side_frame)
        self.auxiliary_views.setSizes([780, 780])
        self.auxiliary_views.setVisible(False)

        self.view_stack = QSplitter(Qt.Orientation.Vertical)
        self.view_stack.addWidget(primary_views)
        self.view_stack.addWidget(self.auxiliary_views)
        self.view_stack.setSizes([960, 0])

        root = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.view_stack)
        root.addWidget(self._build_control_panel())
        root.setSizes([1300, 300])
        self.setCentralWidget(root)
        self._update_auxiliary_visibility()

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_message = QLabel("준비")
        status.addWidget(self.status_message, 1)
        self.calibration_badge = QLabel("Calibration: 확인 중")
        status.addPermanentWidget(self.calibration_badge)

    def _framed(self, title: str, child: QWidget) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        label = QLabel(title)
        label.setStyleSheet("font-weight: 600; padding: 2px;")
        layout.addWidget(label)
        layout.addWidget(child, 1)
        return widget

    def _build_control_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(285)
        layout = QVBoxLayout(panel)

        navigation = QGroupBox("프레임")
        nav_layout = QVBoxLayout(navigation)
        self.frame_combo = QComboBox()
        self.frame_combo.currentTextChanged.connect(self._request_frame)
        nav_layout.addWidget(self.frame_combo)
        buttons = QHBoxLayout()
        previous = QPushButton("◀ 이전")
        previous.clicked.connect(lambda: self._move_frame(-1))
        following = QPushButton("다음 ▶")
        following.clicked.connect(lambda: self._move_frame(1))
        buttons.addWidget(previous)
        buttons.addWidget(following)
        nav_layout.addLayout(buttons)
        self.carry_forward_check = QCheckBox("새로 만든 박스를 다음 프레임으로 이어가기")
        self.carry_forward_check.setChecked(
            bool(self.config["editing"].get("carry_created_boxes_forward", True))
        )
        nav_layout.addWidget(self.carry_forward_check)
        self.frame_info = QLabel()
        nav_layout.addWidget(self.frame_info)
        self.working_path_label = QLabel()
        self.working_path_label.setWordWrap(True)
        self.working_path_label.setStyleSheet("color:#6b7280; font-size:10px;")
        self.working_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        nav_layout.addWidget(self.working_path_label)
        layout.addWidget(navigation)

        self.camera_panel = CameraPanel(self.config["views"])
        self.camera_combo = self.camera_panel.camera_combo
        self.camera_labels_check = self.camera_panel.camera_labels_check
        self.projected_labels_check = self.camera_panel.projected_labels_check
        self.live_projection_check = self.camera_panel.live_projection_check
        self.projection_status = self.camera_panel.projection_status
        self.camera_combo.currentTextChanged.connect(self._render_camera)
        self.camera_labels_check.toggled.connect(self._render_camera)
        self.projected_labels_check.toggled.connect(self._render_camera)
        self.live_projection_check.toggled.connect(self._render_camera)
        layout.addWidget(self.camera_panel)

        side_group = QGroupBox("보조 뷰")
        side_layout = QVBoxLayout(side_group)
        self.bev_visible_check = QCheckBox("BEV 표시 (박스 생성/평면 확인)")
        self.bev_visible_check.setChecked(bool(self.config["views"]["show_bev_auxiliary"]))
        side_layout.addWidget(self.bev_visible_check)
        self.side_visible_check = QCheckBox("측면 표시 (높이 확인)")
        self.side_visible_check.setChecked(
            bool(self.config["views"]["show_side_auxiliary"])
        )
        side_layout.addWidget(self.side_visible_check)
        self.bev_visible_check.toggled.connect(self._update_auxiliary_visibility)
        self.side_visible_check.toggled.connect(self._update_auxiliary_visibility)
        self.side_combo = QComboBox()
        self.side_combo.addItems(["xz", "yz"])
        self.side_combo.currentTextChanged.connect(self._change_side_plane)
        side_layout.addWidget(self.side_combo)
        self.detail_status = QLabel("상세 3D: 객체를 선택하세요.")
        self.detail_status.setWordWrap(True)
        self.detail_status.setStyleSheet("color:#6b7280; font-size:10px;")
        side_layout.addWidget(self.detail_status)
        layout.addWidget(side_group)

        self.sensor_group = QGroupBox("LiDAR 센서")
        self.sensor_layout = QVBoxLayout(self.sensor_group)
        layout.addWidget(self.sensor_group)

        point_group = QGroupBox("포인트 표시")
        point_layout = QFormLayout(point_group)
        self.point_color_combo = QComboBox()
        self.point_color_combo.addItem("센서별", "sensor")
        self.point_color_combo.addItem("높이", "height")
        self.point_color_combo.addItem("Intensity", "intensity")
        self.point_color_combo.addItem("단색", "uniform")
        mode_index = self.point_color_combo.findData(self.config["views"]["point_color_mode"])
        self.point_color_combo.setCurrentIndex(max(0, mode_index))
        self.point_color_combo.currentIndexChanged.connect(self._change_point_display)
        point_layout.addRow("색상", self.point_color_combo)
        self.point_size_spin = QDoubleSpinBox()
        self.point_size_spin.setRange(0.5, 8.0)
        self.point_size_spin.setSingleStep(0.5)
        self.point_size_spin.setValue(float(self.config["views"]["point_size"]))
        self.point_size_spin.valueChanged.connect(self._change_point_display)
        point_layout.addRow("크기", self.point_size_spin)
        self.box_line_width_spin = QDoubleSpinBox()
        self.box_line_width_spin.setRange(0.5, 8.0)
        self.box_line_width_spin.setSingleStep(0.5)
        self.box_line_width_spin.setValue(float(self.config["views"]["box_line_width"]))
        self.box_line_width_spin.valueChanged.connect(self._change_box_display)
        point_layout.addRow("박스 선 두께", self.box_line_width_spin)
        self.object_labels_check = QCheckBox("객체 이름·BEV 크기 표시")
        self.object_labels_check.setToolTip(
            "밀집 프레임은 선택 객체만, 객체가 15개 이하이면 전체 이름표를 표시합니다."
        )
        self.object_labels_check.setChecked(
            bool(self.config["views"].get("show_object_labels", True))
        )
        self.object_labels_check.toggled.connect(self._change_box_display)
        point_layout.addRow(self.object_labels_check)
        self.uniform_color_button = QPushButton("단색 선택")
        self.uniform_color_button.clicked.connect(self._choose_uniform_color)
        self._update_color_button()
        point_layout.addRow("단색", self.uniform_color_button)
        layout.addWidget(point_group)

        create_group = QGroupBox("새 박스 생성")
        create_layout = QFormLayout(create_group)
        self.new_class_combo = QComboBox()
        self.new_class_combo.addItems(
            [str(item["name"]) for item in self.config["classes"]]
        )
        create_layout.addRow("클래스", self.new_class_combo)
        self.create_button = QPushButton("새 박스 만들기 · BEV에서 위치 클릭")
        self.create_button.setCheckable(True)
        self.create_button.setStyleSheet("font-weight:600; padding:7px;")
        self.create_button.toggled.connect(self._toggle_create_mode)
        create_layout.addRow(self.create_button)
        create_help = QLabel("버튼을 누르면 BEV가 자동으로 열립니다. Esc: 취소")
        create_help.setWordWrap(True)
        create_help.setStyleSheet("color:#6b7280; font-size:10px;")
        create_layout.addRow(create_help)
        layout.addWidget(create_group)

        object_group = QGroupBox("객체")
        object_layout = QVBoxLayout(object_group)
        self.object_list = QListWidget()
        self.object_list.setMinimumHeight(180)
        self.object_list.currentItemChanged.connect(self._select_object)
        object_layout.addWidget(self.object_list, 1)
        self.auto_focus_check = QCheckBox("선택 시 3D/보조 뷰에서 자동 이동")
        self.auto_focus_check.setChecked(bool(self.config["views"]["auto_focus_selection"]))
        self.auto_focus_check.toggled.connect(self._toggle_auto_focus)
        object_layout.addWidget(self.auto_focus_check)
        focus_button = QPushButton("선택 객체로 이동")
        focus_button.clicked.connect(self._focus_selected_object)
        object_layout.addWidget(focus_button)
        self.selection_status = QLabel()
        self.selection_status.setWordWrap(True)
        self.selection_status.setStyleSheet("color:#a36b00;")
        object_layout.addWidget(self.selection_status)
        self.object_details = QLabel("선택된 객체 없음")
        self.object_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.object_details.setWordWrap(True)
        object_layout.addWidget(self.object_details)
        layout.addWidget(object_group)

        self.object_editor_panel = ObjectEditorPanel(
            str(item["name"]) for item in self.config["classes"]
        )
        self.class_combo = self.object_editor_panel.class_combo
        self.box_spins = self.object_editor_panel.box_spins
        self.delete_button = self.object_editor_panel.delete_button
        self.undo_button = self.object_editor_panel.undo_button
        self.redo_button = self.object_editor_panel.redo_button
        self.save_button = self.object_editor_panel.save_button
        self.edit_status = self.object_editor_panel.edit_status
        self.class_combo.currentTextChanged.connect(self._commit_editor)
        for spin in self.box_spins.values():
            spin.editingFinished.connect(self._commit_editor)
        self.delete_button.clicked.connect(self._delete_selected)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)
        self.save_button.clicked.connect(self._save_working_label)
        layout.addWidget(self.object_editor_panel)

        quick_help = QGroupBox("빠른 사용법")
        quick_help_layout = QVBoxLayout(quick_help)
        help_text = QLabel(
            "1. 객체 목록·전체 3D·BEV 박스를 클릭해 선택\n"
            "2. W/S: 앞뒤 · A/D: 좌우 · Q/E: 회전\n"
            "3. R/F: 길이 · T/G: 폭 · Y/H: 높이\n"
            "4. ←/→: 이전/다음 프레임\n"
            "5. ‘새 박스 만들기’ 후 열린 BEV에서 위치 클릭\n"
            "6. Ctrl+S 저장 · Ctrl+Z 되돌리기"
        )
        help_text.setWordWrap(True)
        quick_help_layout.addWidget(help_text)
        layout.addWidget(quick_help)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(305)
        scroll.setWidget(panel)
        self._install_shortcuts()
        return scroll

    def _install_shortcuts(self) -> None:
        self.shortcuts: list[QShortcut] = []

        def add(sequence: QKeySequence | QKeySequence.StandardKey, callback: Any) -> None:
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

        add(QKeySequence.StandardKey.Save, self._save_working_label)
        add(QKeySequence.StandardKey.Undo, self._shortcut_undo)
        add(QKeySequence.StandardKey.Redo, self._shortcut_redo)
        add(QKeySequence(Qt.Key.Key_Delete), self._shortcut_delete)
        shortcuts = {
            Qt.Key.Key_W: ("x", 1.0),
            Qt.Key.Key_S: ("x", -1.0),
            Qt.Key.Key_A: ("y", 1.0),
            Qt.Key.Key_D: ("y", -1.0),
            Qt.Key.Key_Q: ("yaw", -1.0),
            Qt.Key.Key_E: ("yaw", 1.0),
            Qt.Key.Key_R: ("length", 1.0),
            Qt.Key.Key_F: ("length", -1.0),
            Qt.Key.Key_T: ("width", 1.0),
            Qt.Key.Key_G: ("width", -1.0),
            Qt.Key.Key_Y: ("height", 1.0),
            Qt.Key.Key_H: ("height", -1.0),
        }
        for key, (field, direction) in shortcuts.items():
            add(
                QKeySequence(key),
                lambda f=field, d=direction: self._nudge_selected(f, d),
            )
        add(QKeySequence(Qt.Key.Key_Left), lambda: self._shortcut_move_frame(-1))
        add(QKeySequence(Qt.Key.Key_Right), lambda: self._shortcut_move_frame(1))
        add(QKeySequence(Qt.Key.Key_N), lambda: self._set_create_from_shortcut(True))
        add(QKeySequence(Qt.Key.Key_Escape), lambda: self._set_create_from_shortcut(False))
        for index, class_config in enumerate(self.config["classes"][:4], start=1):
            add(
                QKeySequence(str(index)),
                lambda name=str(class_config["name"]): self._choose_class_from_shortcut(name),
            )

    def _populate_index(self) -> None:
        self.frame_combo.blockSignals(True)
        self.frame_combo.addItems(self.index.frame_ids)
        self.frame_combo.blockSignals(False)
        for sensor in self.index.lidar_ids:
            check = QCheckBox(sensor)
            check.setChecked(True)
            check.toggled.connect(self._render_clouds)
            self.sensor_layout.addWidget(check)
            self.sensor_checks[sensor] = check

    def _request_frame(self, frame_id: str) -> None:
        if not frame_id:
            return
        if (
            self.payload is not None
            and frame_id != self.payload.source.frame_id
            and not self._resolve_dirty_before_leave()
        ):
            self._clear_pending_carry()
            self.frame_combo.blockSignals(True)
            self.frame_combo.setCurrentText(self.payload.source.frame_id)
            self.frame_combo.blockSignals(False)
            return
        if self._pending_carry_target is not None and frame_id != self._pending_carry_target:
            self._clear_pending_carry()
        self.request_generation += 1
        request = self.request_generation
        self.status_message.setText(f"{frame_id} 불러오는 중…")
        self.frame_combo.setEnabled(False)
        future = self.executor.submit(
            load_frame_payload,
            self.adapter,
            self.importer,
            frame_id,
            self.repository,
        )
        future.add_done_callback(
            lambda completed, req=request, fid=frame_id: self._finish_future(req, fid, completed)
        )

    def _finish_future(
        self, request: int, frame_id: str, future: Future[FrameLoadPayload]
    ) -> None:
        try:
            payload = future.result()
        except Exception as exc:  # UI boundary: details are shown without crashing the app.
            self.bridge.failed.emit(request, frame_id, f"{type(exc).__name__}: {exc}")
        else:
            self.bridge.completed.emit(request, payload)

    def _accept_frame(self, request: int, payload_object: object) -> None:
        if request != self.request_generation:
            return
        payload = payload_object
        if not isinstance(payload, FrameLoadPayload):
            return
        self.payload = payload
        self.history = AnnotationHistory.start(
            payload.label, limit=int(self.config["editing"]["history_limit"])
        )
        recovery_status = self._offer_recovery(payload)
        carried_ids: tuple[str, ...] = ()
        carried_selection: str | None = None
        if (
            recovery_status != "restored"
            and self.carry_forward_check.isChecked()
            and payload.source.frame_id == self._pending_carry_target
            and self._pending_carried_objects
        ):
            merged, carried_ids = merge_carried_objects(
                payload.label, self._pending_carried_objects
            )
            self.history.apply(merged)
            available_ids = {obj.id for obj in merged.objects}
            if self._pending_carried_selection in available_ids:
                carried_selection = self._pending_carried_selection
            elif carried_ids:
                carried_selection = carried_ids[0]
        self._clear_pending_carry()
        current_label = self.history.current
        self.frame_combo.setEnabled(True)
        self._update_frame_summary()
        working_path = self.repository.path_for(payload.source.frame_id)
        try:
            display_path = working_path.relative_to(self.dataset_root)
        except ValueError:
            display_path = working_path
        self.working_path_label.setText(f"작업 저장: {display_path}")
        self.working_path_label.setToolTip(str(working_path))
        self._populate_cameras(payload)
        self._populate_objects(current_label.objects)
        if carried_selection is not None:
            self._select_object_id(carried_selection)
        self._update_sensor_status(payload)
        self._render_all()
        self._update_editor()
        self._update_edit_state()
        point_count = sum(
            cloud.point_count for clouds in payload.clouds.values() for cloud in clouds
        )
        status_text = (
            f"{payload.source.frame_id} · {point_count:,} points · "
            f"{len(current_label.objects)} objects"
            + (f" · 새 박스 {len(carried_ids)}개 이어받음" if carried_ids else "")
            + (" · 복구본 복원됨" if recovery_status == "restored" else "")
        )
        warning_messages = [
            f"{name}: {message}" for name, message in payload.sensor_errors.items()
        ] + [
            f"{name} layer: {message}"
            for name, message in payload.reference_layer_errors.items()
        ]
        if warning_messages:
            status_text += f" · ⚠ 로드 경고 {len(warning_messages)}개"
        self.status_message.setText(status_text)
        self.status_message.setToolTip("\n".join(warning_messages))
        self._update_calibration_badge(payload)

    def _offer_recovery(self, payload: FrameLoadPayload) -> str | None:
        frame_id = payload.source.frame_id
        if frame_id in self._ignored_recovery_frames:
            return None
        result = self.recovery_store.inspect(frame_id)
        if result.error is not None:
            self._ignored_recovery_frames.add(frame_id)
            QMessageBox.warning(
                self,
                "복구 파일을 읽을 수 없음",
                "복구 파일이 손상되었거나 형식이 올바르지 않습니다. "
                "정상 라벨은 그대로 열었습니다.\n\n"
                f"{result.error}\n\n"
                f"파일: {self.recovery_store.path_for(frame_id)}",
            )
            return "invalid"
        snapshot = result.snapshot
        working_path = self.repository.path_for(frame_id)
        if (
            snapshot is None
            or snapshot.dataset_id != self.index.dataset_id
            or not self.recovery_store.is_newer_than_working(frame_id, working_path)
        ):
            return None

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("저장되지 않은 복구본 발견")
        dialog.setText(
            f"{frame_id} 프레임에 저장된 작업 라벨보다 새로운 복구본이 있습니다."
        )
        dialog.setInformativeText(
            f"복구 시각: {snapshot.created_at_utc}\n"
            f"기준 revision: {snapshot.base_revision}\n\n"
            "자동으로 복원하지 않습니다. 수행할 작업을 선택하세요."
        )
        restore_button = dialog.addButton("복구본 복원", QMessageBox.ButtonRole.AcceptRole)
        ignore_button = dialog.addButton("이번 실행에서 무시", QMessageBox.ButtonRole.RejectRole)
        delete_button = dialog.addButton("복구본 삭제", QMessageBox.ButtonRole.DestructiveRole)
        dialog.setDefaultButton(restore_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is restore_button:
            if self.history is not None:
                self.history.apply(snapshot.label)
            return "restored"
        if clicked is delete_button:
            try:
                self.recovery_store.delete(frame_id)
            except OSError as exc:
                QMessageBox.warning(self, "복구본 삭제 실패", str(exc))
            return "deleted"
        if clicked is ignore_button:
            self._ignored_recovery_frames.add(frame_id)
        return "ignored"

    def _write_recovery_snapshot(self) -> None:
        if self.history is None or not self.history.dirty:
            return
        label = self.history.current
        try:
            self.recovery_store.write(
                label,
                base_revision=self.history.baseline.revision,
                working_label_path=self.repository.path_for(label.frame_id),
                tool_version=__version__,
            )
        except (OSError, ValueError) as exc:
            self.status_message.setText(
                f"복구본 저장 실패 · 정상 라벨은 영향 없음 · {type(exc).__name__}: {exc}"
            )

    def _source_sensor_status(self, payload: FrameLoadPayload) -> Mapping[str, Any]:
        source_status = payload.source.metadata.get("sensor_status", {})
        if isinstance(source_status, Mapping) and source_status:
            return source_status
        label_status = payload.label.calibration_state.get("sensor_status", {})
        return label_status if isinstance(label_status, Mapping) else {}

    def _update_calibration_badge(self, payload: FrameLoadPayload) -> None:
        statuses = self._source_sensor_status(payload)
        not_required = [
            sensor for sensor, status in statuses.items() if status == "not_required"
        ]
        applied = [sensor for sensor, status in statuses.items() if status == "applied"]
        issues = [
            f"{sensor} {str(status).title()}"
            for sensor, status in statuses.items()
            if status in {"missing", "invalid", "disabled", "unknown"}
        ]
        if applied:
            lidar_status = f"Applied ({', '.join(applied)})"
        elif not_required:
            lidar_status = f"불필요 ({', '.join(not_required)} · {self.index.reference_frame})"
        else:
            lidar_status = "사용 가능 센서 없음"
        if issues:
            lidar_status += f" · 센서 문제: {', '.join(issues)}"
        if payload.sensor_errors:
            failed_sensors = sorted({name.split(":", 1)[0] for name in payload.sensor_errors})
            lidar_status += f" · Load failed: {', '.join(failed_sensors)}"
        camera_status = (
            "camera projection: 사용 가능"
            if self.camera_calibrations
            else "camera projection: 없음"
        )
        self.calibration_badge.setText(
            f"LiDAR calibration: {lidar_status} · {camera_status}"
        )

    def _update_sensor_status(self, payload: FrameLoadPayload) -> None:
        statuses = self._source_sensor_status(payload)
        display = {
            "not_required": "Not required",
            "applied": "Applied",
            "missing": "Missing",
            "invalid": "Invalid",
            "disabled": "Disabled",
            "load_failed": "Load failed",
            "unknown": "Unknown",
        }
        for sensor, check in self.sensor_checks.items():
            errors = {
                name: message
                for name, message in payload.sensor_errors.items()
                if name.split(":", 1)[0] == sensor
            }
            available = bool(payload.clouds.get(sensor))
            status = "load_failed" if errors else str(statuses.get(sensor, "unknown"))
            suffix = " (일부 return 사용 가능)" if errors and available else ""
            check.setText(f"{sensor} · {display.get(status, status)}{suffix}")
            check.setEnabled(available)
            check.setToolTip(
                "\n".join(f"{name}: {message}" for name, message in errors.items())
                if errors
                else f"Calibration state: {display.get(status, status)}"
            )
            check.setStyleSheet(
                "color:#b45309;" if status in {"missing", "invalid", "disabled", "load_failed"}
                else ""
            )

    def _show_load_error(self, request: int, frame_id: str, message: str) -> None:
        if request != self.request_generation:
            return
        self.frame_combo.setEnabled(True)
        self._clear_pending_carry()
        self.status_message.setText(f"{frame_id} 로드 실패 — {message}")

    def _populate_cameras(self, payload: FrameLoadPayload) -> None:
        previous = self.camera_combo.currentText()
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        self.camera_combo.addItems(sorted(payload.source.image_paths))
        if previous in payload.source.image_paths:
            self.camera_combo.setCurrentText(previous)
        elif "FRONT" in payload.source.image_paths:
            self.camera_combo.setCurrentText("FRONT")
        self.camera_combo.blockSignals(False)

    def _populate_objects(self, objects: Iterable[LabeledObject]) -> None:
        selected_id = self._selected_id()
        self.object_list.blockSignals(True)
        self.object_list.clear()
        selected_row = -1
        for row, obj in enumerate(objects):
            item = QListWidgetItem(f"{obj.class_name:<10}  {obj.id[:12]}")
            item.setData(Qt.ItemDataRole.UserRole, obj.id)
            self.object_list.addItem(item)
            if obj.id == selected_id:
                selected_row = row
        self.object_list.blockSignals(False)
        if selected_row >= 0:
            self.object_list.setCurrentRow(selected_row)

    def _active_clouds(self) -> list[PointCloudData]:
        if self.payload is None:
            return []
        return [
            cloud
            for sensor, clouds in self.payload.clouds.items()
            if self.sensor_checks.get(sensor) is None or self.sensor_checks[sensor].isChecked()
            for cloud in clouds
        ]

    def _render_all(self, *_: Any) -> None:
        if self.payload is None:
            return
        self._render_clouds()
        self._render_boxes_only()
        self._render_camera()

    def _render_clouds(self, *_: Any) -> None:
        if self.payload is None:
            return
        clouds = self._active_clouds()
        max_points = int(self.config["point_cloud"]["max_render_points"])
        point_size = self.point_size_spin.value()
        color_mode = str(self.point_color_combo.currentData())
        self.view_3d.set_clouds(
            clouds,
            max_points=max_points,
            point_size=point_size,
            color_mode=color_mode,
            uniform_color=self.uniform_point_color,
        )
        if self.bev_visible_check.isChecked():
            self.bev_view.set_clouds(
                clouds,
                point_size=point_size,
                color_mode=color_mode,
                uniform_color=self.uniform_point_color,
            )
        if self.side_visible_check.isChecked():
            self.side_view.set_clouds(
                clouds,
                point_size=point_size,
                color_mode=color_mode,
                uniform_color=self.uniform_point_color,
            )
        self._render_detail()

    def _render_boxes_only(self) -> None:
        label = self._current_label()
        if label is None:
            return
        objects = label.objects
        selected_id = self._selected_id()
        line_width = self.box_line_width_spin.value()
        self.view_3d.set_boxes(
            objects,
            selected_id=selected_id,
            line_width=line_width,
            show_labels=self.object_labels_check.isChecked(),
        )
        if self.bev_visible_check.isChecked():
            self.bev_view.set_boxes(
                objects,
                selected_id=selected_id,
                line_width=line_width,
                show_labels=self.object_labels_check.isChecked(),
            )
        if self.side_visible_check.isChecked():
            self.side_view.set_boxes(
                objects, selected_id=selected_id, line_width=line_width
            )
        self._render_detail()

    def _render_detail(self) -> None:
        if self.payload is None:
            return
        selected = self._selected_object()
        count = self.detail_view.set_detail(
            self._active_clouds(),
            selected,
            margin_m=float(self.config["views"]["object_detail_margin_m"]),
            point_size=max(2.0, self.point_size_spin.value()),
            color_mode=str(self.point_color_combo.currentData()),
            uniform_color=self.uniform_point_color,
            box_line_width=self.box_line_width_spin.value(),
            reset_view=self._detail_reset_requested,
            show_labels=self.object_labels_check.isChecked(),
        )
        self._detail_reset_requested = False
        if selected is None:
            self.detail_status.setText("상세 3D: 객체를 선택하세요.")
        else:
            self.detail_status.setText(
                f"상세 3D: {selected.class_name} · 박스 주변 "
                f"{self.config['views']['object_detail_margin_m']:.1f} m · {count:,} points"
            )

    def _render_camera(self, *_: Any) -> None:
        if self.payload is None:
            return
        camera = self.camera_combo.currentText()
        image_path = self.payload.source.image_paths.get(camera)
        if image_path is None:
            self.image_view.clear_image()
            self.projection_status.setText("카메라 이미지 없음")
            return
        camera_labels = (
            self._labels_for_camera(self.payload.reference_layers.get("camera"), camera)
            if self.camera_labels_check.isChecked()
            else ()
        )
        projected_labels = (
            self._labels_for_camera(
                self.payload.reference_layers.get("projected_lidar"), camera
            )
            if self.projected_labels_check.isChecked()
            else ()
        )
        live_wireframes: tuple[ProjectedWireframe, ...] = ()
        calibration = self.camera_calibrations.get(camera)
        if self.live_projection_check.isChecked() and calibration is not None:
            label = self._current_label()
            if label is not None:
                live_wireframes = tuple(
                    project_box_wireframe(
                        obj.id, camera_synced_projection_box(obj), calibration
                    )
                    for obj in label.objects
                )
            self.projection_status.setText(
                f"실시간 투영: {camera} 카메라 보정값 적용 · "
                f"{self.index.reference_frame} frame"
            )
        elif self.live_projection_check.isChecked():
            self.projection_status.setText(
                f"실시간 투영 불가: {camera} camera calibration 없음"
            )
        else:
            self.projection_status.setText("실시간 투영: 꺼짐")
        selected_id = self._selected_id()
        found = self.image_view.set_image(
            image_path,
            camera_labels,
            projected_labels,
            live_wireframes,
            selected_object_id=selected_id,
            camera_id=camera,
            focus_selected=False,
            box_line_width=self.box_line_width_spin.value(),
        )
        if selected_id and not found:
            self.selection_status.setText(
                f"선택 객체는 {camera} 카메라 시야에 투영되지 않습니다."
            )
        else:
            self.selection_status.clear()

    @staticmethod
    def _labels_for_camera(layer: Any, camera: str) -> Iterable[Mapping[str, Any]]:
        if not isinstance(layer, list):
            return ()
        for group in layer:
            if isinstance(group, Mapping) and group.get("name") == camera:
                labels = group.get("labels", ())
                return labels if isinstance(labels, list) else ()
        return ()

    def _selected_id(self) -> str | None:
        item = self.object_list.currentItem() if hasattr(self, "object_list") else None
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _select_object(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        selected_id = (
            str(current.data(Qt.ItemDataRole.UserRole)) if current is not None else None
        )
        selected = None
        label = self._current_label()
        if label is not None and selected_id is not None:
            selected = next(
                (obj for obj in label.objects if obj.id == selected_id), None
            )
        if selected is None:
            self.object_details.setText("선택된 객체 없음")
        else:
            box = selected.box3d
            self.object_details.setText(
                f"ID: {selected.id}\n"
                f"Class: {selected.class_name}\n"
                f"Center: ({box.x:.3f}, {box.y:.3f}, {box.z:.3f})\n"
                f"Size: ({box.length:.3f}, {box.width:.3f}, {box.height:.3f})\n"
                f"Yaw: {box.yaw:.4f} rad"
            )
        self._update_editor(selected)
        self._render_boxes_only()
        self._render_camera()
        if selected is not None and self.auto_focus_check.isChecked():
            self._focus_object(selected)

    def _change_side_plane(self, plane: str) -> None:
        self.side_view.set_plane(plane)
        if self.side_visible_check.isChecked():
            self._render_clouds()
            self._render_boxes_only()

    def _update_auxiliary_visibility(self, *_: Any) -> None:
        show_bev = self.bev_visible_check.isChecked()
        show_side = self.side_visible_check.isChecked()
        self.bev_frame.setVisible(show_bev)
        self.side_frame.setVisible(show_side)
        self.side_combo.setEnabled(show_side)
        self.auxiliary_views.setVisible(show_bev or show_side)
        self.view_stack.setSizes([650, 330] if show_bev or show_side else [980, 0])
        if self.payload is not None and (show_bev or show_side):
            self._render_clouds()
            self._render_boxes_only()
            selected = self._selected_object()
            if selected is not None and self.auto_focus_check.isChecked():
                if show_bev:
                    self.bev_view.focus_on_box(selected.box3d)
                if show_side:
                    self.side_view.focus_on_box(selected.box3d)

    def _change_point_display(self, *_: Any) -> None:
        uniform = self.point_color_combo.currentData() == "uniform"
        self.uniform_color_button.setEnabled(uniform)
        self._render_clouds()

    def _change_box_display(self, *_: Any) -> None:
        self._render_boxes_only()
        self._render_camera()

    def _choose_uniform_color(self) -> None:
        selected = QColorDialog.getColor(QColor(self.uniform_point_color), self, "포인트 색상")
        if not selected.isValid():
            return
        self.uniform_point_color = selected.name().upper()
        self._update_color_button()
        self._render_clouds()

    def _update_color_button(self) -> None:
        self.uniform_color_button.setStyleSheet(
            f"background:{self.uniform_point_color}; color:#111;"
        )
        if hasattr(self, "point_color_combo"):
            self.uniform_color_button.setEnabled(
                self.point_color_combo.currentData() == "uniform"
            )

    def _selected_object(self) -> LabeledObject | None:
        selected_id = self._selected_id()
        label = self._current_label()
        if label is None or selected_id is None:
            return None
        return next((obj for obj in label.objects if obj.id == selected_id), None)

    def _focus_selected_object(self) -> None:
        selected = self._selected_object()
        if selected is not None:
            self._focus_object(selected)
            self._render_camera()

    def _toggle_auto_focus(self, enabled: bool) -> None:
        if enabled:
            selected = self._selected_object()
            if selected is not None:
                self._focus_object(selected)
        self._render_camera()

    def _focus_object(self, selected: LabeledObject) -> None:
        self.view_3d.focus_on_box(selected.box3d)
        if self.bev_visible_check.isChecked():
            self.bev_view.focus_on_box(selected.box3d)
        if self.side_visible_check.isChecked():
            self.side_view.focus_on_box(selected.box3d)

    def _current_label(self) -> FrameLabel | None:
        if self.history is not None:
            return self.history.current
        return self.payload.label if self.payload is not None else None

    def _update_editor(self, selected: LabeledObject | None = None) -> None:
        if selected is None:
            selected = self._selected_object()
        enabled = selected is not None
        self._updating_editor = True
        try:
            self.class_combo.setEnabled(enabled)
            self.delete_button.setEnabled(enabled)
            for spin in self.box_spins.values():
                spin.setEnabled(enabled)
            if selected is None:
                return
            box = selected.box3d
            self.class_combo.setCurrentText(selected.class_name)
            values = {
                "x": box.x,
                "y": box.y,
                "z": box.z,
                "length": box.length,
                "width": box.width,
                "height": box.height,
                "yaw_deg": math.degrees(box.yaw),
            }
            for name, value in values.items():
                self.box_spins[name].setValue(value)
        finally:
            self._updating_editor = False

    def _commit_editor(self, *_: Any) -> None:
        if self._updating_editor:
            return
        selected = self._selected_object()
        label = self._current_label()
        if selected is None or label is None:
            return
        try:
            box = Box3D(
                x=self.box_spins["x"].value(),
                y=self.box_spins["y"].value(),
                z=self.box_spins["z"].value(),
                length=self.box_spins["length"].value(),
                width=self.box_spins["width"].value(),
                height=self.box_spins["height"].value(),
                yaw=math.radians(self.box_spins["yaw_deg"].value()),
            )
        except ValueError as exc:
            self.status_message.setText(f"박스 값 오류 — {exc}")
            self._update_editor(selected)
            return
        edited = replace(selected, class_name=self.class_combo.currentText(), box3d=box)
        objects = tuple(edited if obj.id == selected.id else obj for obj in label.objects)
        self._apply_edited_label(
            replace(label, objects=objects, frame_status="in_progress"), selected.id
        )

    def _toggle_create_mode(self, enabled: bool) -> None:
        if enabled and not self.bev_visible_check.isChecked():
            self.bev_visible_check.setChecked(True)
        self.bev_view.set_create_mode(enabled)
        self.create_button.setText(
            "생성 모드 ON · BEV에서 위치 클릭"
            if enabled
            else "새 박스 만들기 · BEV에서 위치 클릭"
        )
        if enabled:
            selected = self._selected_object()
            if selected is not None:
                self.new_class_combo.setCurrentText(selected.class_name)
            self.status_message.setText("BEV에서 새 3D 박스의 중심을 클릭하세요.")

    def _create_box_at(self, x: float, y: float) -> None:
        self._create_box(x, y)

    def _move_box_from_bev(self, object_id: str, x: float, y: float) -> None:
        self._update_object_box(object_id, x=x, y=y)

    def _resize_box_from_bev(
        self, object_id: str, x: float, y: float, length: float, width: float
    ) -> None:
        self._update_object_box(
            object_id, x=x, y=y, length=length, width=width
        )

    def _rotate_box_from_bev(self, object_id: str, yaw: float) -> None:
        self._update_object_box(object_id, yaw=yaw)

    def _move_box_vertical_from_side(self, object_id: str, z: float) -> None:
        self._update_object_box(object_id, z=z)

    def _resize_box_height_from_side(
        self, object_id: str, z: float, height: float
    ) -> None:
        self._update_object_box(object_id, z=z, height=height)

    def _update_object_box(self, object_id: str, **changes: float) -> None:
        label = self._current_label()
        if label is None:
            return
        selected = next((obj for obj in label.objects if obj.id == object_id), None)
        if selected is None:
            return
        edited = replace(selected, box3d=replace(selected.box3d, **changes))
        objects = tuple(edited if obj.id == object_id else obj for obj in label.objects)
        self._apply_edited_label(
            replace(label, objects=objects, frame_status="in_progress"), object_id
        )

    def _create_box_from_drag(
        self, x: float, y: float, length: float, width: float
    ) -> None:
        self._create_box(x, y, length=length, width=width)

    def _create_box(
        self,
        x: float,
        y: float,
        *,
        length: float | None = None,
        width: float | None = None,
    ) -> None:
        label = self._current_label()
        if label is None:
            return
        class_name = self.new_class_combo.currentText() or str(
            self.config["classes"][0]["name"]
        )
        class_config = next(
            (item for item in self.config["classes"] if item["name"] == class_name),
            self.config["classes"][0],
        )
        default_length, default_width, height = (
            float(value) for value in class_config["default_size"]
        )
        box_length = max(0.05, length if length is not None else default_length)
        box_width = max(0.05, width if width is not None else default_width)
        new_object = LabeledObject(
            id=uuid4().hex,
            class_name=class_name,
            box3d=Box3D(
                x=x,
                y=y,
                z=height / 2.0,
                length=box_length,
                width=box_width,
                height=height,
                yaw=0.0,
            ),
            source={"created_by": "lidar_label_tool"},
        )
        self._detail_reset_requested = True
        self.create_button.setChecked(False)
        self._apply_edited_label(
            replace(
                label,
                objects=label.objects + (new_object,),
                frame_status="in_progress",
            ),
            new_object.id,
        )

    def _delete_selected(self, *_: Any) -> None:
        selected = self._selected_object()
        label = self._current_label()
        if selected is None or label is None:
            return
        row = self.object_list.currentRow()
        objects = tuple(obj for obj in label.objects if obj.id != selected.id)
        next_id = objects[min(max(row, 0), len(objects) - 1)].id if objects else None
        self._apply_edited_label(
            replace(label, objects=objects, frame_status="in_progress"), next_id
        )

    def _apply_edited_label(self, label: FrameLabel, selected_id: str | None) -> None:
        if self.history is None or not self.history.apply(label):
            return
        self._refresh_after_edit(selected_id)

    def _refresh_after_edit(self, selected_id: str | None = None) -> None:
        label = self._current_label()
        if label is None:
            return
        self._populate_objects(label.objects)
        self._select_object_id(selected_id)
        self._render_boxes_only()
        self._render_camera()
        self._update_editor()
        self._update_edit_state()

    def _select_object_id(self, object_id: object) -> None:
        if object_id is None:
            self.object_list.clearSelection()
            self.object_list.setCurrentRow(-1)
            return
        target = str(object_id)
        for row in range(self.object_list.count()):
            item = self.object_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == target:
                self.object_list.setCurrentRow(row)
                return

    def _undo(self, *_: Any) -> None:
        if self.history is None or not self.history.can_undo:
            return
        selected_id = self._selected_id()
        self.history.undo()
        self._refresh_after_edit(selected_id)

    def _redo(self, *_: Any) -> None:
        if self.history is None or not self.history.can_redo:
            return
        selected_id = self._selected_id()
        self.history.redo()
        self._refresh_after_edit(selected_id)

    def _update_edit_state(self) -> None:
        dirty = bool(self.history and self.history.dirty)
        working_exists = bool(self.payload and self.payload.label_origin == "working")
        if dirty:
            status_text = "저장되지 않은 변경 있음"
        elif not working_exists:
            status_text = "작업 라벨 미생성 · 저장하면 새 JSON 생성"
        else:
            status_text = "변경 없음"
        self.edit_status.setText(status_text)
        self.edit_status.setStyleSheet("color:#d97706;" if dirty else "color:#6b7280;")
        self.save_button.setEnabled(dirty or not working_exists)
        self.save_button.setText("작업 라벨 생성" if not working_exists else "저장")
        self.undo_button.setEnabled(bool(self.history and self.history.can_undo))
        self.redo_button.setEnabled(bool(self.history and self.history.can_redo))
        self.setWindowTitle(f"{'* ' if dirty else ''}{self.base_window_title}")
        self._update_frame_summary()

    def _update_frame_summary(self) -> None:
        label = self._current_label()
        if label is None or not hasattr(self, "frame_info"):
            return
        position = self.frame_combo.findText(label.frame_id) + 1
        dirty = bool(self.history and self.history.dirty)
        if dirty:
            origin = "작업 중"
        elif self.payload and self.payload.label_origin == "working":
            origin = "작업 라벨"
        else:
            origin = "원본 라벨"
        state = "미저장" if dirty else f"revision {label.revision}"
        self.frame_info.setText(
            f"{position}/{self.frame_combo.count()} · {label.frame_id}\n"
            f"{len(label.objects)}개 객체 · {origin} · {state}"
        )

    def _save_working_label(self, *_: Any) -> bool:
        if self.history is None:
            return True
        if (
            not self.history.dirty
            and self.payload is not None
            and self.payload.label_origin == "working"
        ):
            return True
        try:
            saved = self.repository.save(self.history.current)
        except (OSError, ValueError, LabelConflictError) as exc:
            self.status_message.setText(f"저장 실패 — {type(exc).__name__}: {exc}")
            QMessageBox.critical(
                self,
                "라벨 저장 실패",
                "기존 라벨은 보존되었습니다.\n\n"
                f"{type(exc).__name__}: {exc}",
            )
            return False
        self.history.mark_saved(saved)
        if self.payload is not None:
            self.payload = replace(self.payload, label=saved, label_origin="working")
        recovery_warning = ""
        try:
            self.recovery_store.delete(saved.frame_id)
        except OSError as exc:
            recovery_warning = f" · 복구본 삭제 실패: {exc}"
        self.status_message.setText(
            f"저장 완료 · revision {saved.revision} · "
            f"{self.repository.path_for(saved.frame_id)}{recovery_warning}"
        )
        self._update_edit_state()
        return True

    def _resolve_dirty_before_leave(self, *, confirm_close: bool = False) -> bool:
        if self.history is None or not self.history.dirty:
            return True
        if bool(self.config["editing"]["autosave_on_frame_change"]):
            return self._save_working_label()
        answer = QMessageBox.question(
            self,
            "저장되지 않은 변경",
            "현재 프레임의 변경 사항을 저장하시겠습니까?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._save_working_label()
        if answer == QMessageBox.StandardButton.Discard:
            return True
        return False

    def _nudge_selected(self, field: str, direction: float) -> None:
        if self._shortcut_blocked():
            return
        selected = self._selected_object()
        label = self._current_label()
        if selected is None or label is None:
            return
        box = selected.box3d
        if field == "yaw":
            step = math.radians(float(self.config["editing"]["yaw_step_deg"]))
        elif field in {"length", "width", "height"}:
            step = float(self.config["editing"]["resize_step_m"])
        else:
            fine = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            key = "fine_move_step_m" if fine else "move_step_m"
            step = float(self.config["editing"][key])
        value = getattr(box, field) + direction * step
        if field in {"length", "width", "height"}:
            value = max(0.01, value)
        edited_box = replace(box, **{field: value})
        edited = replace(selected, box3d=edited_box)
        objects = tuple(edited if obj.id == selected.id else obj for obj in label.objects)
        self._apply_edited_label(
            replace(label, objects=objects, frame_status="in_progress"), selected.id
        )

    @staticmethod
    def _shortcut_blocked() -> bool:
        focus = QApplication.focusWidget()
        return isinstance(focus, (QLineEdit, QComboBox))

    @staticmethod
    def _text_input_focused() -> bool:
        return isinstance(QApplication.focusWidget(), (QLineEdit, QComboBox))

    def _shortcut_move_frame(self, delta: int) -> None:
        if not self._text_input_focused():
            self._move_frame(delta)

    def _shortcut_undo(self) -> None:
        if not self._text_input_focused():
            self._undo()

    def _shortcut_redo(self) -> None:
        if not self._text_input_focused():
            self._redo()

    def _shortcut_delete(self) -> None:
        if not self._text_input_focused():
            self._delete_selected()

    def _set_create_from_shortcut(self, enabled: bool) -> None:
        if not self._text_input_focused():
            self.create_button.setChecked(enabled)

    def _choose_class_from_shortcut(self, class_name: str) -> None:
        if not self._text_input_focused():
            if self.create_button.isChecked() or self._selected_object() is None:
                self.new_class_combo.setCurrentText(class_name)
            else:
                self.class_combo.setCurrentText(class_name)

    def _move_frame(self, delta: int) -> None:
        target = min(max(self.frame_combo.currentIndex() + delta, 0), self.frame_combo.count() - 1)
        if target != self.frame_combo.currentIndex():
            if delta == 1 and self.carry_forward_check.isChecked():
                label = self._current_label()
                self._pending_carry_target = self.frame_combo.itemText(target)
                self._pending_carried_objects = (
                    created_objects(label.objects) if label is not None else ()
                )
                self._pending_carried_selection = self._selected_id()
            else:
                self._clear_pending_carry()
            self.frame_combo.setCurrentIndex(target)

    def _clear_pending_carry(self) -> None:
        self._pending_carry_target = None
        self._pending_carried_objects = ()
        self._pending_carried_selection = None

    def closeEvent(self, event: Any) -> None:
        if not self._closing and not self._resolve_dirty_before_leave(confirm_close=True):
            event.ignore()
            return
        self._closing = True
        self.recovery_timer.stop()
        self.request_generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.session_lock is not None:
            try:
                released = self.session_lock.release()
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    "세션 잠금 해제 실패",
                    f"프로그램은 종료하지만 잠금 파일을 삭제하지 못했습니다.\n\n{exc}",
                )
            else:
                if not released:
                    self.status_message.setText(
                        "세션 잠금이 다른 세션으로 교체되어 현재 잠금을 삭제하지 않았습니다."
                    )
        super().closeEvent(event)
