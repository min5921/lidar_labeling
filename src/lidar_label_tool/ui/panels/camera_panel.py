from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QLabel, QVBoxLayout


class CameraPanel(QGroupBox):
    """Camera/layer controls without dataset or rendering responsibilities."""

    def __init__(self, view_config: Mapping[str, Any]) -> None:
        super().__init__("카메라 / 레이어")
        layout = QVBoxLayout(self)

        self.camera_combo = QComboBox()
        layout.addWidget(self.camera_combo)

        self.camera_labels_check = QCheckBox("원본 카메라 2D")
        self.camera_labels_check.setChecked(
            bool(view_config["show_source_camera_labels"])
        )
        layout.addWidget(self.camera_labels_check)

        self.projected_labels_check = QCheckBox("원본 LiDAR 투영 2D")
        self.projected_labels_check.setChecked(
            bool(view_config["show_projected_lidar_labels"])
        )
        layout.addWidget(self.projected_labels_check)

        self.live_projection_check = QCheckBox("현재 3D 박스 실시간 투영")
        self.live_projection_check.setChecked(bool(view_config["show_live_projection"]))
        layout.addWidget(self.live_projection_check)

        legend = QLabel(
            '<span style="color:#ffb020">■</span> Camera GT: 독립 2D 라벨<br>'
            '<span style="color:#00dcff">■</span> Source projected: 원본 참조<br>'
            '<span style="color:#28eb6e">■</span> Live 3D: 현재 작업 박스 투영'
        )
        legend.setToolTip(
            "두 레이어는 객체 ID와 생성 시점이 달라 완전히 겹치지 않을 수 있습니다."
        )
        layout.addWidget(legend)

        self.projection_status = QLabel()
        self.projection_status.setWordWrap(True)
        self.projection_status.setStyleSheet("color:#6b7280; font-size:10px;")
        layout.addWidget(self.projection_status)
