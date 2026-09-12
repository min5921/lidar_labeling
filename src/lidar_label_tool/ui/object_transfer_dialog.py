from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.io.labels.object_source import SavedObjectSource
from lidar_label_tool.services.object_transfer import ObjectTransferPlan, plan_object_transfer


class ObjectTransferDialog(QDialog):
    """Preview a batch of saved objects before importing into the current frame."""

    def __init__(
        self, source: SavedObjectSource, target: FrameLabel,
        allowed_classes: Iterable[str], parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.target = target
        self.allowed_classes = tuple(allowed_classes)
        self.plan: ObjectTransferPlan | None = None
        self.setWindowTitle("이전 폴더의 객체 가져오기")
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        summary = QLabel(
            f"이전: {source.dataset_id} · 프레임 {source.frame_id} · {len(source.objects)}개 객체\n"
            f"현재: {target.dataset_id} · 프레임 {target.frame_id}\n"
            f"파일: {source.path}\n\n"
            "같은 LiDAR·좌표계의 연속 데이터에서 사용하세요. ID·박스를 그대로 가져온 뒤 "
            "현재 포인트에 맞춰 위치를 조정하세요. 기존 ID는 유지합니다."
        )
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.table = QTableWidget(len(source.objects), 5)
        self.table.setHorizontalHeaderLabels(["선택", "클래스", "객체 ID", "중심 x / y / z (m)", "처리"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        existing_ids = {obj.id for obj in target.objects}
        for row, obj in enumerate(source.objects):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, check)
            duplicate = obj.id in existing_ids
            if duplicate:
                check.setFlags(Qt.ItemFlag.NoItemFlags)
            values = (
                obj.class_name, obj.id,
                f"{obj.box3d.x:.3f} / {obj.box3d.y:.3f} / {obj.box3d.z:.3f}",
                "기존 ID · 건너뜀" if duplicate else "추가",
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = buttons.addButton("선택 객체 가져오기", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.itemChanged.connect(self._update_plan)
        self._update_plan()

    def _update_plan(self) -> None:
        ids = tuple(
            obj.id for row, obj in enumerate(self.source.objects)
            if (item := self.table.item(row, 0)) is not None
            and item.checkState() == Qt.CheckState.Checked
        )
        try:
            self.plan = plan_object_transfer(
                self.source, self.target, allowed_classes=self.allowed_classes, selected_ids=ids,
            )
        except ValueError as exc:
            self.plan = None
            self.status_label.setText(str(exc))
        else:
            self.status_label.setText(
                f"추가 {len(self.plan.additions)}개 · 기존 ID 건너뜀 {len(self.plan.skipped_ids)}개\n"
                "가져오기는 현재 프레임의 편집입니다. Ctrl+Z: 전체 취소 · Ctrl+S: 저장"
            )
        self.import_button.setEnabled(self.plan is not None and bool(self.plan.additions))
