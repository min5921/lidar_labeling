from __future__ import annotations

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
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
                    window.object_list.setCurrentRow(0)
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
