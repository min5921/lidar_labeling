from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
import hashlib
import json
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.services.frame_session import LabelContextIssue
from lidar_label_tool.ui.main_window import MainWindow
from tests.fixture_builders import create_v2_dataset


@pytest.fixture
def camera_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "카메라 보정 변경"
    root.mkdir()
    manifest = create_v2_dataset(root, with_camera=True)
    calibration = {
        "schema_version": "1.0",
        "reference_frame": "lidar:AEVA",
        "lidars": {"aeva": {"T_reference_sensor": np.eye(4).tolist()}},
        "cameras": {
            "head_camera": {
                "intrinsic": [[20, 0, 16], [0, 20, 12], [0, 0, 1]],
                "T_camera_reference": np.eye(4).tolist(),
                "image_size": [32, 24],
                "distortion_model": "none",
            },
        },
    }
    calibration_path = root / "calibration.json"
    calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
    manifest["profiles"][0]["camera"].update({
        "mode": "calibrated",
        "calibration_path": "calibration.json",
        "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
    })
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    with patch.object(MainWindow, "_request_frame"):
        window = MainWindow(root, default_config_path(), profile_id="aeva_profile")
    window.frame_combo.currentTextChanged.disconnect()
    window.frame_combo.currentTextChanged.connect(window._request_frame)

    def load_immediately(function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    with patch.object(window.executor, "submit", side_effect=load_immediately):
        window._request_frame("000000")
        window._create_box(10, 0)
        window.live_projection_check.setChecked(True)
        yield window, calibration_path
    window._closing = True
    window.close()
    app.processEvents()


@pytest.mark.parametrize("change", ["changed", "missing"])
def test_render_discards_old_projection_after_calibration_changes(camera_window, change):
    window, path = camera_window
    before = window.history.current
    assert window.camera_calibrations
    assert window.image_view._overlay_items
    if change == "changed":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path.unlink()
    with patch("lidar_label_tool.ui.main_window.project_box_wireframe") as project:
        window._render_camera()
        project.assert_not_called()
    assert not window.camera_calibrations
    assert not window.image_view._overlay_items
    assert "다시 여세요" in window.projection_status.text()
    assert "비활성" in window.calibration_badge.text()
    assert window.history.current == before
    window._nudge_selected("z", 1)
    assert window._selected_object().box3d.z > before.objects[0].box3d.z


def test_save_cancel_removes_stale_projection_without_touching_label(camera_window):
    window, path = camera_window
    assert window._save_working_label()
    label_path = window.repository.path_for("000000")
    saved_bytes = label_path.read_bytes()
    window._nudge_selected("z", 1)
    path.write_text("broken calibration", encoding="utf-8")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
        assert not window._save_working_label()
    assert not window.camera_calibrations
    assert not window.image_view._overlay_items
    assert label_path.read_bytes() == saved_bytes
    assert window.history.dirty


def test_first_save_with_changed_calibration_stays_lidar_editable_and_records_invalid_state(camera_window):
    window, path = camera_window
    path.write_text("broken calibration", encoding="utf-8")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        assert window._save_working_label()
    saved = window.repository.load("000000")
    assert saved.calibration_state["effective_mode"] == "display_only"
    assert saved.calibration_state["status"] == "invalid"
    assert window.frame_combo.isEnabled()
    assert not window.camera_calibrations
    assert not window.image_view._overlay_items


def test_next_unsaved_frame_receives_runtime_calibration_warning(camera_window):
    window, path = camera_window
    assert window._save_working_label()
    path.write_bytes(path.read_bytes() + b" ")
    with patch.object(QMessageBox, "warning") as warning:
        window._move_frame(1)
    assert window.payload.source.frame_id == "000001"
    assert "calibration_runtime_changed" in {issue.code for issue in window.payload.context_issues}
    assert not window.camera_calibrations
    assert not window.image_view._overlay_items
    assert window.frame_combo.isEnabled()
    warning.assert_called_once()


def test_saved_label_calibration_warning_does_not_invalidate_current_loaded_matrices(camera_window):
    window, _ = camera_window
    original_cache = dict(window.camera_calibrations)
    issue = LabelContextIssue("calibration_changed", "saved label is older than current calibration")
    assert not window._invalidate_camera_projection((issue,))
    window._render_camera()
    assert window.camera_calibrations == original_cache
    assert window._projection_disabled_reason is None
    assert window.image_view._overlay_items


def test_unreadable_calibration_warning_invalidates_projection_before_frame_render(camera_window):
    window, _ = camera_window
    payload = replace(
        window.payload,
        context_issues=(LabelContextIssue("calibration_fingerprint_unreadable", "permission denied"),),
    )
    with (
        patch.object(QMessageBox, "warning"),
        patch("lidar_label_tool.ui.main_window.project_box_wireframe") as project,
    ):
        window._accept_frame(window.request_generation, payload)
        project.assert_not_called()
    assert not window.camera_calibrations
    assert not window.image_view._overlay_items
    assert window.frame_combo.isEnabled()
