from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
)


_BOX_FIELD_SPECS = {
    "x": (-1000.0, 1000.0, 0.1, 3),
    "y": (-1000.0, 1000.0, 0.1, 3),
    "z": (-1000.0, 1000.0, 0.1, 3),
    "length": (0.01, 100.0, 0.1, 3),
    "width": (0.01, 100.0, 0.1, 3),
    "height": (0.01, 100.0, 0.1, 3),
    "yaw_deg": (-180.0, 180.0, 1.0, 2),
}


class ObjectEditorPanel(QGroupBox):
    """Box value widgets; MainWindow remains responsible for edit commands."""

    def __init__(self, class_names: Iterable[str]) -> None:
        super().__init__("3D 박스 편집")
        layout = QFormLayout(self)

        self.class_combo = QComboBox()
        self.class_combo.addItems(list(class_names))
        layout.addRow("클래스", self.class_combo)

        self.box_spins: dict[str, QDoubleSpinBox] = {}
        for name, (minimum, maximum, step, decimals) in _BOX_FIELD_SPECS.items():
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setKeyboardTracking(False)
            self.box_spins[name] = spin
            layout.addRow("Yaw (도)" if name == "yaw_deg" else name, spin)

        self.delete_button = QPushButton("삭제")
        layout.addRow(self.delete_button)

        self.fit_floor_button = QPushButton("포인트 바닥에 맞춤")
        self.fit_floor_button.setToolTip(
            "선택 박스의 XY footprint 안쪽 포인트를 기준으로 z를 자동 보정합니다."
        )
        layout.addRow(self.fit_floor_button)

        history_row = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.save_button = QPushButton("저장")
        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        history_row.addWidget(self.save_button)
        layout.addRow(history_row)

        self.edit_status = QLabel("변경 없음")
        self.edit_status.setWordWrap(True)
        layout.addRow(self.edit_status)
