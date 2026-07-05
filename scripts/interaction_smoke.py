from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.geometry.box3d import bev_corners
from lidar_label_tool.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="GUI interaction regression smoke test")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--frame", default="000006")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    result: dict[str, object] = {"phase": "load", "error": None}

    with TemporaryDirectory(prefix="lidar-label-tool-smoke-") as workspace:
        window = MainWindow(
            args.dataset,
            default_config_path(),
            workspace_root=Path(workspace),
        )
        window.show()
        window.frame_combo.setCurrentText(args.frame)
        created_id: str | None = None
        expected_detail_pose: tuple[float, float, float] | None = None
        target_frame: str | None = None

        def widget_point(view: object, x: float, y: float) -> QPoint:
            scene_position = view.getViewBox().mapViewToScene(QPointF(x, y))
            return view.mapFromScene(scene_position)

        def drag(view: object, start: QPoint, end: QPoint) -> None:
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(view.viewport(), end, delay=20)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            app.processEvents()

        def fail(message: str) -> None:
            result["error"] = message
            window.close()
            app.quit()

        def poll() -> None:
            nonlocal created_id, expected_detail_pose, target_frame
            try:
                phase = result["phase"]
                if phase == "load":
                    if window.payload is None or window.payload.source.frame_id != args.frame:
                        return
                    if window.object_list.count() == 0:
                        fail("source frame has no object to select")
                        return
                    label = window._current_label()
                    preferred = next(
                        (obj for obj in label.objects if obj.class_name == "Car"),
                        label.objects[0] if label and label.objects else None,
                    )
                    if preferred is None:
                        fail("source frame has no selectable object")
                        return
                    window._select_object_id(preferred.id)
                    selected = window._selected_object()
                    if selected is None:
                        fail("object selection failed")
                        return

                    window.detail_view.setCameraPosition(
                        distance=17.0, elevation=41.0, azimuth=-35.0
                    )
                    expected_detail_pose = (
                        float(window.detail_view.opts["distance"]),
                        float(window.detail_view.opts["elevation"]),
                        float(window.detail_view.opts["azimuth"]),
                    )
                    window._render_detail()
                    actual_pose = (
                        float(window.detail_view.opts["distance"]),
                        float(window.detail_view.opts["elevation"]),
                        float(window.detail_view.opts["azimuth"]),
                    )
                    if actual_pose != expected_detail_pose:
                        fail("detail view pose reset during ordinary render")
                        return

                    original_x = selected.box3d.x
                    original_length = selected.box3d.length
                    window.view_3d.setFocus()
                    QTest.keyClick(window.view_3d, Qt.Key.Key_W)
                    QTest.keyClick(window.view_3d, Qt.Key.Key_R)
                    app.processEvents()
                    moved = window._selected_object()
                    if (
                        moved is None
                        or moved.box3d.x <= original_x
                        or moved.box3d.length <= original_length
                    ):
                        fail("W/R shortcuts did not move and resize the selected box")
                        return

                    window.bev_visible_check.setChecked(True)
                    window.bev_view.focus_on_box(moved.box3d)
                    app.processEvents()
                    before_drag = moved.box3d
                    start = widget_point(window.bev_view, before_drag.x, before_drag.y)
                    end = QPoint(start.x() + 40, start.y() + 25)
                    drag(window.bev_view, start, end)
                    after_drag = window._selected_object()
                    if after_drag is None or (
                        after_drag.box3d.x == before_drag.x
                        and after_drag.box3d.y == before_drag.y
                    ):
                        fail("BEV selected-box drag did not move x/y")
                        return
                    if (
                        after_drag.box3d.z != before_drag.z
                        or after_drag.box3d.length != before_drag.length
                        or after_drag.box3d.width != before_drag.width
                        or after_drag.box3d.height != before_drag.height
                        or after_drag.box3d.yaw != before_drag.yaw
                    ):
                        fail("BEV drag changed a box field other than x/y")
                        return
                    window._undo()
                    restored = window._selected_object()
                    if restored is None or (
                        restored.box3d.x != before_drag.x
                        or restored.box3d.y != before_drag.y
                    ):
                        fail("one Undo did not restore the complete BEV drag")
                        return
                    window._redo()
                    moved = window._selected_object()
                    if moved is None:
                        fail("Redo after BEV drag lost selection")
                        return

                    before_resize = moved
                    corner = bev_corners(before_resize.box3d)[0]
                    resize_start = widget_point(
                        window.bev_view, float(corner[0]), float(corner[1])
                    )
                    resize_end = widget_point(
                        window.bev_view, float(corner[0] + 0.8), float(corner[1] + 0.6)
                    )
                    drag(window.bev_view, resize_start, resize_end)
                    resized = window._selected_object()
                    if resized is None or (
                        resized.box3d.length == before_resize.box3d.length
                        and resized.box3d.width == before_resize.box3d.width
                    ):
                        fail("BEV corner handle did not resize length/width")
                        return
                    if (
                        resized.box3d.z != before_resize.box3d.z
                        or resized.box3d.height != before_resize.box3d.height
                        or resized.box3d.yaw != before_resize.box3d.yaw
                        or resized.id != before_resize.id
                        or resized.class_name != before_resize.class_name
                        or resized.attributes != before_resize.attributes
                        or resized.source != before_resize.source
                    ):
                        fail("BEV resize did not preserve non-planar/object fields")
                        return
                    window._undo()
                    if window._selected_object() != before_resize:
                        fail("one Undo did not restore the complete BEV resize")
                        return
                    window._redo()
                    resized = window._selected_object()
                    assert resized is not None

                    *_, rotate_x, rotate_y = window.bev_view._rotate_handle_geometry(
                        resized.box3d
                    )
                    radius = math.hypot(
                        rotate_x - resized.box3d.x, rotate_y - resized.box3d.y
                    )
                    target_yaw = resized.box3d.yaw + 0.35
                    rotate_start = widget_point(window.bev_view, rotate_x, rotate_y)
                    rotate_end = widget_point(
                        window.bev_view,
                        resized.box3d.x + math.cos(target_yaw) * radius,
                        resized.box3d.y + math.sin(target_yaw) * radius,
                    )
                    before_rotate = resized
                    drag(window.bev_view, rotate_start, rotate_end)
                    rotated = window._selected_object()
                    if rotated is None or rotated.box3d.yaw == before_rotate.box3d.yaw:
                        fail("BEV rotate handle did not update yaw")
                        return
                    if (
                        rotated.box3d.x != before_rotate.box3d.x
                        or rotated.box3d.y != before_rotate.box3d.y
                        or rotated.box3d.length != before_rotate.box3d.length
                        or rotated.box3d.width != before_rotate.box3d.width
                        or rotated.box3d.height != before_rotate.box3d.height
                    ):
                        fail("BEV rotation changed fields other than yaw")
                        return
                    window._undo()
                    if window._selected_object() != before_rotate:
                        fail("one Undo did not restore the BEV rotation")
                        return
                    window._redo()

                    window.side_visible_check.setChecked(True)
                    side_object = window._selected_object()
                    assert side_object is not None
                    window.side_view.focus_on_box(side_object.box3d)
                    app.processEvents()
                    axis_value = (
                        side_object.box3d.x
                        if window.side_view.plane == "xz"
                        else side_object.box3d.y
                    )
                    vertical_start = widget_point(
                        window.side_view, axis_value, side_object.box3d.z
                    )
                    vertical_end = widget_point(
                        window.side_view, axis_value, side_object.box3d.z + 0.5
                    )
                    before_vertical = side_object
                    drag(window.side_view, vertical_start, vertical_end)
                    vertical = window._selected_object()
                    if vertical is None or vertical.box3d.z == before_vertical.box3d.z:
                        fail("SideView body drag did not move z")
                        return
                    if (
                        vertical.box3d.x != before_vertical.box3d.x
                        or vertical.box3d.y != before_vertical.box3d.y
                        or vertical.box3d.length != before_vertical.box3d.length
                        or vertical.box3d.width != before_vertical.box3d.width
                        or vertical.box3d.height != before_vertical.box3d.height
                        or vertical.box3d.yaw != before_vertical.box3d.yaw
                    ):
                        fail("SideView vertical move changed a field other than z")
                        return
                    window._undo()
                    if window._selected_object() != before_vertical:
                        fail("one Undo did not restore the SideView z move")
                        return
                    window._redo()

                    vertical = window._selected_object()
                    assert vertical is not None
                    axis_value = (
                        vertical.box3d.x
                        if window.side_view.plane == "xz"
                        else vertical.box3d.y
                    )
                    top = vertical.box3d.z + vertical.box3d.height / 2.0
                    height_start = widget_point(window.side_view, axis_value, top)
                    height_end = widget_point(window.side_view, axis_value, top + 0.5)
                    before_height = vertical
                    drag(window.side_view, height_start, height_end)
                    heightened = window._selected_object()
                    if heightened is None or heightened.box3d.height <= before_height.box3d.height:
                        fail("SideView top handle did not increase height")
                        return
                    if (
                        heightened.box3d.x != before_height.box3d.x
                        or heightened.box3d.y != before_height.box3d.y
                        or heightened.box3d.length != before_height.box3d.length
                        or heightened.box3d.width != before_height.box3d.width
                        or heightened.box3d.yaw != before_height.box3d.yaw
                    ):
                        fail("SideView height resize changed horizontal fields")
                        return
                    window._undo()
                    if window._selected_object() != before_height:
                        fail("one Undo did not restore the SideView height resize")
                        return
                    window._redo()

                    picked = None
                    for y in range(20, max(21, window.view_3d.height()), 20):
                        for x in range(20, max(21, window.view_3d.width()), 20):
                            picked = window.view_3d._pick_object(float(x), float(y))
                            if picked is not None:
                                break
                        if picked is not None:
                            break
                    if picked is None:
                        fail("full 3D projected-box picking found no clickable box")
                        return
                    window._select_object_id(picked)
                    if window._selected_id() != picked:
                        fail("full 3D picked ID did not synchronize to object list")
                        return

                    selected = window._selected_object()
                    assert selected is not None
                    window._create_box(selected.box3d.x + 2.0, selected.box3d.y + 2.0)
                    created_id = window._selected_id()
                    if created_id is None:
                        fail("new box creation did not select the created object")
                        return
                    window.detail_view.setCameraPosition(
                        distance=19.0, elevation=36.0, azimuth=-22.0
                    )
                    expected_detail_pose = (
                        float(window.detail_view.opts["distance"]),
                        float(window.detail_view.opts["elevation"]),
                        float(window.detail_view.opts["azimuth"]),
                    )
                    target_index = window.frame_combo.currentIndex() + 1
                    target_frame = window.frame_combo.itemText(target_index)
                    window.view_3d.setFocus()
                    QTest.keyClick(window.view_3d, Qt.Key.Key_Right)
                    result["phase"] = "carry"
                    return

                if phase == "carry":
                    if (
                        window.payload is None
                        or target_frame is None
                        or window.payload.source.frame_id != target_frame
                    ):
                        return
                    label = window._current_label()
                    if label is None or created_id not in {obj.id for obj in label.objects}:
                        fail("created box was not carried to the next frame")
                        return
                    if window._selected_id() != created_id:
                        fail("carried box selection was not restored")
                        return
                    actual_pose = (
                        float(window.detail_view.opts["distance"]),
                        float(window.detail_view.opts["elevation"]),
                        float(window.detail_view.opts["azimuth"]),
                    )
                    if actual_pose != expected_detail_pose:
                        fail("detail view pose reset on frame transition")
                        return
                    result["phase"] = "done"
                    window.close()
                    app.quit()
            except Exception as exc:  # Smoke-test boundary should report a concise failure.
                fail(f"{type(exc).__name__}: {exc}")

        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(100)
        QTimer.singleShot(args.timeout_ms, lambda: fail("interaction smoke timed out"))
        app.exec()
        window.close()

    if result["error"] is not None:
        print(result["error"], file=sys.stderr)
        return 1
    print("interaction smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
