from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QVector3D
from PySide6.QtWidgets import QApplication, QMessageBox

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.ui.main_window import MainWindow
from lidar_label_tool.workers.frame_loader import load_frame_payload
from tests.fixture_builders import create_v2_dataset


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "한글 프레임 편집"
    root.mkdir()
    create_v2_dataset(root, frame_count=3)
    with patch.object(MainWindow, "_request_frame"):
        editor = MainWindow(root, default_config_path(), profile_id="aeva_profile")
    editor.frame_combo.currentTextChanged.disconnect()
    editor.frame_combo.currentTextChanged.connect(editor._request_frame)

    def run_immediately(function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    # Use the real frame loader and completion handler without timing-dependent threads.
    with patch.object(editor.executor, "submit", side_effect=run_immediately):
        editor._request_frame("000000")
        yield editor
    editor._closing = True
    editor.close()
    app.processEvents()


def _view_state(window):
    params = window.view_3d.cameraParams()
    center = params["center"]
    return (
        (center.x(), center.y(), center.z()),
        tuple(params[name] for name in ("distance", "elevation", "azimuth", "fov")),
        np.array(window.bev_view.viewRange()),
        np.array(window.side_view.viewRange()),
    )


def _set_custom_views(window):
    window.bev_visible_check.setChecked(True)
    window.side_visible_check.setChecked(True)
    window.view_3d.setCameraPosition(
        pos=QVector3D(24, -9, 3), distance=37, elevation=56, azimuth=34,
    )
    window.bev_view.setRange(xRange=(8, 20), yRange=(-10, 7), padding=0)
    window.side_view.setRange(xRange=(12, 22), yRange=(-3, 6), padding=0)
    return _view_state(window)


def _assert_views_equal(window, expected):
    actual = _view_state(window)
    assert actual[0] == expected[0]
    assert actual[1] == expected[1]
    np.testing.assert_allclose(actual[2], expected[2])
    np.testing.assert_allclose(actual[3], expected[3])


@pytest.mark.parametrize("carry", [True, False])
def test_save_forward_backward_and_jump_preserve_main_and_bev_view(window, carry):
    window._create_box(1, 2)
    obj = window._selected_object()
    assert obj is not None
    window.carry_forward_check.setChecked(carry)
    for frame_id in ("000001", "000002"):
        if carry and frame_id == "000001":
            continue
        source = window.adapter.load_source_frame(frame_id)
        target = window.importer.import_laser_labels(source)
        moved = replace(obj, box3d=replace(obj.box3d, x=20))
        window.repository.save(replace(target, objects=(moved,)))
    window.auto_focus_check.setChecked(True)
    expected = _set_custom_views(window)
    assert window._save_working_label()
    _assert_views_equal(window, expected)

    window._move_frame(1)
    assert window.payload.source.frame_id == "000001"
    assert window._selected_id() == obj.id
    _assert_views_equal(window, expected)
    window._move_frame(-1)
    assert window.payload.source.frame_id == "000000"
    _assert_views_equal(window, expected)
    window.frame_combo.setCurrentText("000002")
    assert window.payload.source.frame_id == "000002"
    _assert_views_equal(window, expected)

    window._focus_selected_object()
    assert _view_state(window)[0] != expected[0]


def test_floor_shortcut_changes_only_z_and_supports_undo(window):
    window._create_box(1, 2)
    original = window._selected_object()
    cloud = window._active_clouds()[0]
    points = np.array([[1, 2, -0.25]] * 16, dtype=np.float32)
    floor_cloud = replace(cloud, xyz=points, attributes={})
    shortcut = next(s for s in window.shortcuts if s.key() == QKeySequence(Qt.Key.Key_B))

    with patch.object(window, "_active_clouds", return_value=[floor_cloud]):
        shortcut.activated.emit()
    assert window._selected_object().box3d == replace(
        original.box3d, z=-0.25 + original.box3d.height / 2,
    )
    window._undo()
    assert window._selected_object() == original
    np.testing.assert_array_equal(points, [[1, 2, -0.25]] * 16)


def test_floor_shortcut_ignores_text_entry_and_missing_points(window):
    window._create_box(1, 2)
    before = window.history.current
    shortcut = next(s for s in window.shortcuts if s.key() == QKeySequence(Qt.Key.Key_B))
    with patch.object(QApplication, "focusWidget", return_value=window.box_spins["z"].lineEdit()):
        shortcut.activated.emit()
    assert window.history.current == before
    # The fixture has only one point, below the floor estimator's minimum.
    shortcut.activated.emit()
    assert window.history.current == before
    assert "부족" in window.status_message.text()


def test_reference_can_be_copied_backward_saved_and_reloaded(window):
    window.frame_combo.setCurrentText("000002")
    window._create_box(1, 2)
    obj = window._selected_object()
    window.remember_object_button.click()
    assert window._save_working_label()
    source_path = window.repository.path_for("000002")
    source_bytes = source_path.read_bytes()

    window._move_frame(-1)
    assert window.copy_reference_button.isEnabled()
    window.copy_reference_button.click()
    assert window._selected_id() == obj.id
    assert window._selected_object().box3d == obj.box3d
    assert window.history.dirty
    assert not window.copy_reference_button.isEnabled()
    window._undo()
    assert window.history.current.objects == ()
    window._redo()
    assert window.history.current.objects[0].id == obj.id
    assert window._save_working_label()
    window._request_frame("000001")
    assert window.history.current.objects[0].id == obj.id
    assert source_path.read_bytes() == source_bytes


def test_existing_object_link_keeps_box_and_source_metadata_after_save(window):
    window.frame_combo.setCurrentText("000002")
    window._create_box(1, 2)
    reference_id = window._selected_id()
    window.remember_object_button.click()
    window._move_frame(-1)
    window._create_box(10, -4)
    original = window._selected_object()
    original = replace(original, source={"raw": {"id": original.id}}, extra_fields={"vendor": 2})
    window._apply_edited_label(replace(window.history.current, objects=(original,)), original.id)

    window.link_object_button.click()
    linked = window._selected_object()
    assert linked.id == reference_id
    assert linked.box3d == original.box3d
    assert linked.source == original.source
    assert linked.extra_fields["vendor"] == 2
    window._undo()
    assert window.history.current.objects == (original,)
    window._redo()
    assert window.history.current.objects[0] == linked
    assert window._save_working_label()
    window._request_frame("000001")
    assert window.history.current.objects[0] == linked


def test_link_save_failure_preserves_previous_file_and_dirty_edit(window):
    window.frame_combo.setCurrentText("000002")
    window._create_box(1, 2)
    window.remember_object_button.click()
    window._move_frame(-1)
    window._create_box(10, 2)
    assert window._save_working_label()
    path = window.repository.path_for("000001")
    saved_bytes = path.read_bytes()
    window.link_object_button.click()
    with (
        patch.object(window.repository, "save", side_effect=OSError("disk full")),
        patch.object(QMessageBox, "critical"),
    ):
        assert not window._save_working_label()
    assert window.history.dirty
    assert path.read_bytes() == saved_bytes


def test_loading_blocks_link_edits_and_failure_restores_visible_frame(window):
    window._create_box(1, 2)
    window.remember_object_button.click()
    with patch.object(window.executor, "submit", return_value=Future()):
        window._move_frame(1)
    before = window.history.current
    assert not window.remember_object_button.isEnabled()
    assert not window.copy_reference_button.isEnabled()
    window._copy_reference_to_frame()
    window._link_selected_to_reference()
    assert window.history.current == before
    window._show_load_error(window.request_generation, "000001", "missing")
    assert window.frame_combo.currentText() == "000000"
    assert window.remember_object_button.isEnabled()


def test_stale_loaded_frame_does_not_reset_views_or_reference(window):
    window._create_box(1, 2)
    window.remember_object_button.click()
    reference = window._object_link_reference
    expected = _set_custom_views(window)
    stale = load_frame_payload(window.adapter, window.importer, "000001", window.repository)
    window._accept_frame(window.request_generation - 1, stale)
    assert window.payload.source.frame_id == "000000"
    assert window._object_link_reference is reference
    _assert_views_equal(window, expected)
