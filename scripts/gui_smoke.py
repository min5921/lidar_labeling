from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    parser.add_argument("--capture-delay-ms", type=int, default=1_200)
    parser.add_argument("--frame")
    parser.add_argument("--camera")
    parser.add_argument("--select-visible", action="store_true")
    parser.add_argument("--select-id-prefix")
    parser.add_argument("--exercise-edit", action="store_true")
    parser.add_argument("--create-mode", action="store_true")
    parser.add_argument("--show-bev", action="store_true")
    parser.add_argument("--show-side", action="store_true")
    parser.add_argument(
        "--point-color-mode", choices=["sensor", "height", "intensity", "uniform"]
    )
    parser.add_argument("--point-size", type=float)
    parser.add_argument("--box-line-width", type=float)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(args.dataset, default_config_path())
    window.show()
    if args.frame:
        window.frame_combo.setCurrentText(args.frame)
    result = {"loaded": False, "configured": False}

    def capture() -> None:
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.output)):
                raise RuntimeError(f"failed to save screenshot: {args.output}")
        window.close()
        app.quit()

    def poll() -> None:
        if window.payload is None:
            return
        if args.frame and window.payload.source.frame_id != args.frame:
            return
        result["loaded"] = True
        if result["configured"]:
            return
        result["configured"] = True
        if args.point_color_mode:
            index = window.point_color_combo.findData(args.point_color_mode)
            window.point_color_combo.setCurrentIndex(index)
        if args.point_size is not None:
            window.point_size_spin.setValue(args.point_size)
        if args.box_line_width is not None:
            window.box_line_width_spin.setValue(args.box_line_width)
        if args.camera:
            window.camera_combo.setCurrentText(args.camera)
        if args.select_id_prefix:
            for row in range(window.object_list.count()):
                item = window.object_list.item(row)
                if str(item.data(Qt.ItemDataRole.UserRole)).startswith(args.select_id_prefix):
                    window.object_list.setCurrentRow(row)
                    break
        elif args.select_visible:
            camera = window.camera_combo.currentText()
            labels = window._labels_for_camera(
                window.payload.reference_layers.get("projected_lidar"), camera
            )
            projected_ids = {
                str(label.get("id", "")).removesuffix(f"_{camera}") for label in labels
            }
            for row in range(window.object_list.count()):
                item = window.object_list.item(row)
                if str(item.data(Qt.ItemDataRole.UserRole)) in projected_ids:
                    window.object_list.setCurrentRow(row)
                    break
        if args.exercise_edit:
            if window.object_list.currentRow() < 0 and window.object_list.count():
                window.object_list.setCurrentRow(0)
            selected = window._selected_object()
            if selected is None:
                raise RuntimeError("edit smoke test could not select an object")
            original_x = selected.box3d.x
            window._nudge_selected("x", 1.0)
            moved = window._selected_object()
            if moved is None or moved.box3d.x == original_x or not window.history.dirty:
                raise RuntimeError("edit smoke test did not create a dirty edit")
            window._undo()
            restored = window._selected_object()
            if restored is None or restored.box3d.x != original_x or window.history.dirty:
                raise RuntimeError("edit smoke test undo did not restore the baseline")
        if args.create_mode:
            window.create_button.setChecked(True)
        elif args.show_bev:
            window.bev_visible_check.setChecked(True)
        if args.show_side:
            window.side_visible_check.setChecked(True)
        QTimer.singleShot(args.capture_delay_ms, capture)

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(100)
    QTimer.singleShot(args.timeout_ms, app.quit)
    app.exec()
    window.close()
    return 0 if result["loaded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
