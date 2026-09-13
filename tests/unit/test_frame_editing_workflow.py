from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
import json
from unittest.mock import patch

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent, QVector3D, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.services.object_tracking import TrackingResult
from lidar_label_tool.ui.main_window import MainWindow
from lidar_label_tool.ui.object_transfer_dialog import ObjectTransferDialog
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
    assert not window.import_objects_button.isEnabled()
    window._copy_reference_to_frame()
    window._link_selected_to_reference()
    with patch("lidar_label_tool.ui.main_window.QFileDialog.getOpenFileName") as picker:
        window._import_previous_label_objects()
        picker.assert_not_called()
    assert window.history.current == before
    window._show_load_error(window.request_generation, "000001", "missing")
    assert window.frame_combo.currentText() == "000000"
    assert window.remember_object_button.isEnabled()
    assert window.import_objects_button.isEnabled()


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


def _previous_folder_label(window, tmp_path):
    objects = tuple(
        LabeledObject(
            f"track-{index}", "car", Box3D(index + 1, 2, 1, 4, 2, 1.6, 0),
            source={"raw": {"id": f"track-{index}"}},
        )
        for index in range(2)
    )
    previous = replace(
        window.history.current, dataset_id="previous_chunk", frame_id="000999",
        revision=1, objects=objects, frame_status="reviewed",
        point_cloud_paths={"aeva": ("previous/000999.bin",)},
    )
    path = tmp_path / "이전 폴더 000999.json"
    path.write_text(json.dumps(previous.to_dict()), encoding="utf-8")
    return path


def test_import_button_carries_multiple_objects_across_folder_boundary(window, tmp_path):
    path = _previous_folder_label(window, tmp_path)
    original_bytes = path.read_bytes()
    with (
        patch("lidar_label_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch.object(ObjectTransferDialog, "exec", return_value=QDialog.DialogCode.Accepted),
    ):
        window.import_objects_button.click()
    assert [obj.id for obj in window.history.current.objects] == ["track-0", "track-1"]
    assert window.history.current.frame_id == "000000"
    assert window.history.current.dataset_id == "ds_fixture_v2"
    window._undo()
    assert window.history.current.objects == ()
    window._redo()
    assert len(window.history.current.objects) == 2
    assert window._save_working_label()
    saved = window.repository.load("000000")
    assert [obj.id for obj in saved.objects] == ["track-0", "track-1"]
    window._move_frame(1)
    assert window.payload.source.frame_id == "000001"
    assert [obj.id for obj in window.history.current.objects] == ["track-0", "track-1"]
    assert path.read_bytes() == original_bytes


def test_imported_objects_can_be_followed_one_at_a_time_without_prefilling_others(window, tmp_path):
    path = _previous_folder_label(window, tmp_path)
    source_bytes = path.read_bytes()
    with (
        patch("lidar_label_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch.object(ObjectTransferDialog, "exec", return_value=QDialog.DialogCode.Accepted),
    ):
        window.import_objects_button.click()
    imported = window.history.current.objects
    window.tracking_check.setChecked(True)

    def matched(request, target, clouds):
        # An unselected box must not already exist when its own pass begins.
        assert request.obj.id not in {obj.id for obj in target.objects}
        return TrackingResult(
            request.obj.id, request.source_frame_id, target.frame_id,
            replace(request.obj.box3d, x=request.obj.box3d.x + 1), "matched", "추적됨", score=.9,
        )

    with patch("lidar_label_tool.workers.frame_loader.track_object", side_effect=matched):
        window._select_object_id("track-0")
        window._move_frame(1)
        first_pass = window._selected_object()
        assert [obj.id for obj in window.history.current.objects] == ["track-0"]
        window._move_frame(1)
        assert [obj.id for obj in window.history.current.objects] == ["track-0"]
        assert [obj.id for obj in window.repository.load("000001").objects] == ["track-0"]

        window.frame_combo.setCurrentText("000000")
        assert window.history.current.objects == imported
        window._select_object_id("track-1")
        window._move_frame(1)
        assert window.payload.tracking_result.status == "matched"
        assert window.history.current.objects[0] == first_pass
        assert window._selected_object().box3d.x == imported[1].box3d.x + 1
        window._undo()
        assert window._selected_object() == imported[1]
        assert window.history.current.objects[0] == first_pass
        window._undo()
        assert window.history.current.objects == (first_pass,)
        window._redo()
        window._redo()
        window._select_object_id("track-1")
        window._move_frame(1)
        assert window.payload.tracking_result.status == "matched"
        assert window._selected_object().box3d.x == imported[1].box3d.x + 2
    assert window._save_working_label()
    assert [obj.id for obj in window.repository.load("000002").objects] == ["track-0", "track-1"]
    assert path.read_bytes() == source_bytes


def test_tracking_enabled_with_no_selection_does_not_copy_imported_objects(window, tmp_path):
    path = _previous_folder_label(window, tmp_path)
    with (
        patch("lidar_label_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch.object(ObjectTransferDialog, "exec", return_value=QDialog.DialogCode.Accepted),
    ):
        window.import_objects_button.click()
    window.tracking_check.setChecked(True)
    window._select_object_id(None)
    window._move_frame(1)
    assert window.history.current.objects == ()
    assert window.payload.tracking_result is None


@pytest.mark.parametrize("mode", ["cancel", "source_changed", "frame_changed"])
def test_cancelled_or_stale_import_does_not_modify_current_label(window, tmp_path, mode):
    path = _previous_folder_label(window, tmp_path)
    before = window.history.current

    def finish_dialog():
        if mode == "cancel":
            return QDialog.DialogCode.Rejected
        if mode == "source_changed":
            path.write_bytes(path.read_bytes() + b" ")
        else:
            window.request_generation += 1
        return QDialog.DialogCode.Accepted

    with (
        patch("lidar_label_tool.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")),
        patch.object(ObjectTransferDialog, "exec", side_effect=finish_dialog),
        patch.object(QMessageBox, "warning") as warning,
    ):
        window.import_objects_button.click()
    assert window.history.current == before
    assert not window.history.dirty
    assert warning.call_count == (0 if mode == "cancel" else 1)


def _tracking_scene(window):
    rng = np.random.default_rng(8)
    box = Box3D(10, 2, 3.5, 2, 0.25, 1, 0)
    xyz = (rng.uniform(-0.45, 0.45, (550, 3)) * [2, 0.25, 1] + [10, 2, 3.5]).astype(np.float32)
    cloud = PointCloudData(xyz, {}, "aeva", "1", window.history.current.reference_frame, window.dataset_root / "test.bin")
    obj = LabeledObject("tracked", "car", box, attributes={"name": "elevated board"}, source={"raw": {"keep": True}})
    window.payload = replace(window.payload, clouds={"aeva": (cloud,)})
    window._apply_edited_label(replace(window.history.current, objects=(obj,)), obj.id)
    return obj, cloud


def test_next_frame_tracking_is_undoable_and_preserves_suspended_object(window):
    obj, cloud = _tracking_scene(window)
    window.tracking_check.setChecked(True)
    assert not window.ground_tracking_check.isChecked()
    expected_views = _set_custom_views(window)
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -0.5, 0.18])):
        window._move_frame(1)
    tracked = window._selected_object()
    assert tracked.id == obj.id
    assert tracked.box3d.x == pytest.approx(obj.box3d.x + 1.1, abs=0.15)
    assert tracked.box3d.z == pytest.approx(obj.box3d.z + 0.18, abs=0.15)
    assert tracked.box3d.height == obj.box3d.height
    assert tracked.source == obj.source
    assert "추적" in window.status_message.text()
    _assert_views_equal(window, expected_views)
    window._undo()
    assert window._selected_object().box3d == obj.box3d
    window._redo()
    assert window._selected_object() == tracked
    assert window._save_working_label()
    saved = window.repository.load("000001")
    assert saved.objects[0].box3d == tracked.box3d
    assert saved.objects[0].extra_fields["tracking_history"][-1]["ground_contact"] is False


def _existing_tracking_target(window, obj, status="in_progress"):
    existing = replace(
        obj, box3d=replace(obj.box3d, x=25, length=2.2, height=1.2, yaw=.1),
        attributes={"target-note": "keep"}, source={"raw": {"target": [1]}},
        extra_fields={"unknown_target": True},
    )
    other = replace(existing, id="already-labeled-other", box3d=replace(existing.box3d, x=40))
    target = window.importer.import_laser_labels(window.adapter.load_source_frame("000001"))
    target = window.repository.save(replace(target, objects=(existing, other), frame_status=status))
    return target


def test_retracking_existing_box_is_opt_in_undoable_and_preserves_other_saved_objects(window):
    obj, cloud = _tracking_scene(window)
    target = _existing_tracking_target(window, obj)
    window.tracking_check.setChecked(True)
    assert not window.retrack_existing_check.isChecked()
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -.5, .18])):
        window._move_frame(1)
    assert window.payload.tracking_result.status == "existing_label"
    assert window.history.current.objects == target.objects
    assert not window.history.dirty

    window._move_frame(-1)
    window.payload = replace(window.payload, clouds={"aeva": (cloud,)})
    window._select_object_id(obj.id)
    window.retrack_existing_check.setChecked(True)
    source_bytes = window.repository.path_for("000000").read_bytes()
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -.5, .18])):
        window._move_frame(1)
    assert window.payload.tracking_result.status == "matched"
    tracked = window._selected_object()
    assert tracked.id == obj.id
    assert tracked.box3d.x == pytest.approx(obj.box3d.x + 1.1, abs=.15)
    assert tracked.box3d.z == pytest.approx(obj.box3d.z + .18, abs=.15)
    assert replace(tracked.box3d, x=25, y=obj.box3d.y, z=obj.box3d.z) == target.objects[0].box3d
    assert tracked.attributes == target.objects[0].attributes
    assert tracked.source == target.objects[0].source
    assert tracked.extra_fields["unknown_target"] is True
    assert window.history.current.objects[1] == target.objects[1]
    window._undo()
    assert window.history.current.objects == target.objects
    assert not window.history.dirty
    window._redo()
    assert window._selected_object() == tracked
    assert window._save_working_label()
    window._request_frame("000001")
    assert window.history.current.objects == (tracked, target.objects[1])
    assert window.repository.load("000001").objects == (tracked, target.objects[1])
    assert window.repository.path_for("000000").read_bytes() == source_bytes


@pytest.mark.parametrize("status", ["reviewed", "skipped"])
def test_retracking_option_does_not_change_completed_existing_frame(window, status):
    obj, cloud = _tracking_scene(window)
    target = _existing_tracking_target(window, obj, status)
    before = window.repository.path_for("000001").read_bytes()
    window.tracking_check.setChecked(True)
    window.retrack_existing_check.setChecked(True)
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -.5, .18])):
        window._move_frame(1)
    assert window.payload.tracking_result.status == "protected_label"
    assert window.history.current.objects == target.objects
    assert window.history.current.frame_status == status
    assert not window.history.dirty
    assert window.repository.path_for("000001").read_bytes() == before
    # Reopen is an explicit user action, not an implicit side effect of retracking.
    window.reopen_review_button.click()
    assert window._save_working_label()
    window._move_frame(-1)
    window.payload = replace(window.payload, clouds={"aeva": (cloud,)})
    window._select_object_id(obj.id)
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -.5, .18])):
        window._move_frame(1)
    assert window.payload.tracking_result.status == "matched"
    assert window.history.current.objects[1] == target.objects[1]
    assert window.history.current.frame_status == "in_progress"


def test_failed_retracking_save_preserves_previous_file_and_keeps_undo(window):
    obj, cloud = _tracking_scene(window)
    target = _existing_tracking_target(window, obj)
    before = window.repository.path_for("000001").read_bytes()
    window.tracking_check.setChecked(True)
    window.retrack_existing_check.setChecked(True)
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1.1, -.5, .18])):
        window._move_frame(1)
    assert window.payload.tracking_result.status == "matched"
    with (
        patch.object(window.repository, "save", side_effect=OSError("disk full")),
        patch.object(QMessageBox, "critical"),
    ):
        assert not window._save_working_label()
    assert window.repository.path_for("000001").read_bytes() == before
    assert window.history.dirty
    window._undo()
    assert window.history.current.objects == target.objects


def test_retracking_is_remembered_only_for_the_opted_in_object(window):
    obj, _ = _tracking_scene(window)
    other = replace(obj, id="other-board")
    window._apply_edited_label(replace(window.history.current, objects=(obj, other)), obj.id)
    window.tracking_check.setChecked(True)
    assert not window.retrack_existing_check.isChecked()
    window.retrack_existing_check.setChecked(True)
    window._select_object_id(other.id)
    assert not window.retrack_existing_check.isChecked()
    window._select_object_id(obj.id)
    assert window.retrack_existing_check.isChecked()
    window.retrack_existing_check.setChecked(False)
    assert window._retrack_existing_ids == set()


def test_ground_tracking_is_remembered_per_object_not_shared_with_next_selection(window):
    obj, _ = _tracking_scene(window)
    other = replace(obj, id="other-board")
    window._apply_edited_label(replace(window.history.current, objects=(obj, other)), obj.id)
    window.tracking_check.setChecked(True)
    window.ground_tracking_check.setChecked(True)
    assert obj.id in window._ground_tracking_ids
    window._select_object_id(other.id)
    assert not window.ground_tracking_check.isChecked()
    window._select_object_id(obj.id)
    assert window.ground_tracking_check.isChecked()
    window.ground_tracking_check.setChecked(False)
    assert obj.id not in window._ground_tracking_ids


def test_auto_ground_then_b_does_not_lower_box_or_add_an_undo_step(window):
    from lidar_label_tool.geometry.box_fit import fit_box_bottom_to_points
    from tests.unit.test_object_tracking import scene

    request, _, target_clouds = scene(ground=True)

    def on_slope(cloud):
        xyz = cloud.xyz.copy()
        xyz[:, 2] += 0.03 * (xyz[:, 0] - request.obj.box3d.x)
        return replace(cloud, xyz=xyz, source_frame=window.history.current.reference_frame)

    source_cloud = on_slope(request.clouds[0])
    target_cloud = on_slope(target_clouds[0])
    source_before, target_before = source_cloud.xyz.copy(), target_cloud.xyz.copy()
    original_box = fit_box_bottom_to_points(request.obj.box3d, (source_cloud,))
    assert original_box is not None
    obj = replace(request.obj, box3d=original_box)
    window.payload = replace(window.payload, clouds={"aeva": (source_cloud,)})
    window._apply_edited_label(replace(window.history.current, objects=(obj,)), obj.id)
    window.tracking_check.setChecked(True)
    window.ground_tracking_check.setChecked(True)

    with patch.object(window.adapter, "load_cloud_from_source", return_value=target_cloud):
        window._move_frame(1)

    assert window.payload.tracking_result.ground_applied
    tracked = window._selected_object()
    assert tracked.id == obj.id
    assert tracked.box3d.x == pytest.approx(obj.box3d.x + 1.1, abs=0.15)
    assert tracked.box3d == fit_box_bottom_to_points(tracked.box3d, (target_cloud,))
    shortcut = next(s for s in window.shortcuts if s.key() == QKeySequence(Qt.Key.Key_B))
    for _ in range(2):
        shortcut.activated.emit()
        assert window._selected_object() == tracked
    window._undo()
    assert window._selected_object().box3d == original_box
    window._redo()
    assert window._selected_object() == tracked
    assert window._save_working_label()
    assert window.repository.load("000001").objects[0] == tracked
    np.testing.assert_array_equal(source_cloud.xyz, source_before)
    np.testing.assert_array_equal(target_cloud.xyz, target_before)


def test_pending_tracking_can_be_cancelled_and_cannot_apply_to_a_later_frame(window):
    _, cloud = _tracking_scene(window)
    window.tracking_check.setChecked(True)
    with patch.object(window.executor, "submit", return_value=Future()):
        window._move_frame(1)
    request = window._pending_tracking
    generation = window.request_generation
    assert request is not None
    before = window.history.current
    window._nudge_selected("z", 1)
    window._undo()
    assert window.history.current == before
    with patch.object(window.adapter, "load_cloud_from_source", return_value=replace(cloud, xyz=cloud.xyz + [1, 0, 0])):
        payload = load_frame_payload(window.adapter, window.importer, "000001", window.repository, request)
    with patch.object(window.executor, "submit", return_value=Future()):
        window._request_frame("000002")
    assert request.cancel.is_set()
    window._accept_frame(generation, payload)
    assert window.payload.source.frame_id == "000000"
    assert window.history.current == before
    window._show_load_error(window.request_generation, "000002", "cancelled test")


def test_highlight_checkbox_and_box_move_update_all_visible_views(window):
    obj, _ = _tracking_scene(window)
    window.bev_visible_check.setChecked(True)
    window.side_visible_check.setChecked(True)
    window._render_all()
    for view in (window.view_3d, window.bev_view, window.side_view, window.detail_view):
        assert view.selected_point_count > 0
    window.highlight_points_check.setChecked(False)
    for view in (window.view_3d, window.bev_view, window.side_view, window.detail_view):
        assert view.selected_point_count == 0
    window.highlight_points_check.setChecked(True)
    window._apply_edited_label(replace(window.history.current, objects=(replace(obj, box3d=replace(obj.box3d, z=10)),)), obj.id)
    for view in (window.view_3d, window.bev_view, window.side_view, window.detail_view):
        assert view.selected_point_count == 0


def test_tracking_save_cancel_leaves_original_frame_and_does_not_start_worker(window):
    obj, _ = _tracking_scene(window)
    window.tracking_check.setChecked(True)
    with (
        patch.object(window, "_resolve_dirty_before_leave", return_value=False),
        patch.object(window.executor, "submit") as submit,
    ):
        window._move_frame(1)
        submit.assert_not_called()
    assert window.frame_combo.currentText() == "000000"
    assert window._selected_object().box3d == obj.box3d
    assert window._pending_tracking is None


def test_tracking_worker_failure_keeps_carried_box_and_frame_usable(window):
    obj, _ = _tracking_scene(window)
    window.tracking_check.setChecked(True)
    with patch("lidar_label_tool.workers.frame_loader.track_object", side_effect=RuntimeError("tracking failure")):
        window._move_frame(1)
    assert window.payload.source.frame_id == "000001"
    assert window._selected_object().box3d == obj.box3d
    assert window.frame_combo.isEnabled()
    assert "추적 계산 실패" in window.status_message.text()


def _control_event(event_type):
    modifiers = (
        Qt.KeyboardModifier.ControlModifier
        if event_type == QEvent.Type.KeyPress
        else Qt.KeyboardModifier.NoModifier
    )
    return QKeyEvent(event_type, Qt.Key.Key_Control, modifiers)


@pytest.mark.parametrize("hover", [False, True])
def test_native_control_release_lowers_box_once_and_round_trips(window, hover):
    window._create_box(1, 2)
    original = window._selected_object()
    window.move_step_spin.setValue(0.25)
    # Native key events visit QWindow before being forwarded to its QWidget.
    # Sending directly to a QWidget misses that real keyboard delivery path.
    window.winId()
    handle = window.windowHandle()
    with patch.object(QApplication, "focusWidget", return_value=window.view_3d):
        QTest.keyPress(handle, Qt.Key.Key_Control)
        assert window._selected_object() == original
        if hover:
            move = QMouseEvent(
                QEvent.Type.MouseMove, QPointF(30, 30), QPointF(30, 30),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            QApplication.sendEvent(window.view_3d, move)
        QTest.keyRelease(handle, Qt.Key.Key_Control)
    lowered = replace(original, box3d=replace(original.box3d, z=original.box3d.z - 0.25))
    assert window._selected_object() == lowered
    window._undo()
    assert window._selected_object() == original
    window._redo()
    assert window._selected_object() == lowered
    assert window._save_working_label()
    assert window.repository.load("000000").objects == (lowered,)
    window._request_frame("000000")
    assert window._selected_object() == lowered


@pytest.mark.parametrize("key", [Qt.Key.Key_S, Qt.Key.Key_Z, Qt.Key.Key_Y, Qt.Key.Key_Shift])
def test_native_control_chord_does_not_lower_box(window, key):
    window.winId()
    handle = window.windowHandle()
    with patch.object(window, "_nudge_selected") as nudge:
        QTest.keyPress(handle, Qt.Key.Key_Control)
        # A registered Qt shortcut may consume KeyPress, leaving only this event.
        QApplication.sendEvent(handle, QKeyEvent(
            QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.ControlModifier,
        ))
        QTest.keyRelease(handle, Qt.Key.Key_Control)
    nudge.assert_not_called()


@pytest.mark.parametrize("chord", [False, True])
def test_repeated_control_events_preserve_tap_or_cancelled_chord_until_final_release(window, chord):
    window.winId()
    handle = window.windowHandle()
    with patch.object(window, "_nudge_selected") as nudge:
        QTest.keyPress(handle, Qt.Key.Key_Control)
        if chord:
            QApplication.sendEvent(handle, QKeyEvent(
                QEvent.Type.ShortcutOverride, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier,
            ))
        for event_type in (QEvent.Type.KeyRelease, QEvent.Type.KeyPress):
            QApplication.sendEvent(handle, QKeyEvent(
                event_type, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier, "", True,
            ))
        nudge.assert_not_called()
        QTest.keyRelease(handle, Qt.Key.Key_Control)
        if chord:
            nudge.assert_not_called()
        else:
            nudge.assert_called_once_with("z", -1.0)


@pytest.mark.parametrize("event_type", [
    QEvent.Type.ApplicationDeactivate, QEvent.Type.WindowDeactivate,
])
def test_native_control_does_not_lower_box_after_deactivation(window, event_type):
    window.winId()
    handle = window.windowHandle()
    with patch.object(window, "_nudge_selected") as nudge:
        QTest.keyPress(handle, Qt.Key.Key_Control)
        QApplication.sendEvent(handle, QEvent(event_type))
        QTest.keyRelease(handle, Qt.Key.Key_Control)
    nudge.assert_not_called()


def test_native_control_does_not_edit_box_while_text_input_has_focus(window):
    window._create_box(1, 2)
    original = window._selected_object()
    window.winId()
    with patch.object(QApplication, "focusWidget", return_value=window.frame_combo):
        QTest.keyClick(window.windowHandle(), Qt.Key.Key_Control)
    assert window._selected_object() == original


@pytest.mark.parametrize("modifiers", [
    Qt.KeyboardModifier.ShiftModifier,
    Qt.KeyboardModifier.AltModifier,
    Qt.KeyboardModifier.MetaModifier,
])
def test_control_with_an_already_held_modifier_is_not_control_alone(window, modifiers):
    with patch.object(window, "_nudge_selected") as nudge:
        QApplication.sendEvent(window.view_3d, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Control,
            modifiers | Qt.KeyboardModifier.ControlModifier,
        ))
        QApplication.sendEvent(window.view_3d, _control_event(QEvent.Type.KeyRelease))
    nudge.assert_not_called()


def test_control_with_an_already_held_mouse_button_does_not_lower_box(window):
    with (
        patch.object(window, "_nudge_selected") as nudge,
        patch.object(QApplication, "mouseButtons", return_value=Qt.MouseButton.LeftButton),
    ):
        QApplication.sendEvent(window.view_3d, _control_event(QEvent.Type.KeyPress))
        QApplication.sendEvent(window.view_3d, _control_event(QEvent.Type.KeyRelease))
    nudge.assert_not_called()


def test_control_wheel_changes_only_view_not_selected_box_z(window):
    window._create_box(1, 2)
    original = window._selected_object()
    original_fov = window.view_3d.opts["fov"]
    wheel = QWheelEvent(
        QPointF(30, 30), QPointF(30, 30), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    with patch.object(QApplication, "focusWidget", return_value=window.view_3d):
        QApplication.sendEvent(window.view_3d, _control_event(QEvent.Type.KeyPress))
        QApplication.sendEvent(window.view_3d, wheel)
        QApplication.sendEvent(window.view_3d, _control_event(QEvent.Type.KeyRelease))
    assert window.view_3d.opts["fov"] != original_fov
    assert window._selected_object() == original


@pytest.mark.parametrize("pointer_event", [
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseMove,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.TabletPress,
    QEvent.Type.TouchBegin,
])
def test_control_pointer_gesture_is_not_control_alone(window, pointer_event):
    with patch.object(window, "_nudge_selected") as nudge:
        window.eventFilter(window.view_3d, _control_event(QEvent.Type.KeyPress))
        window.eventFilter(window.view_3d, QEvent(pointer_event))
        window.eventFilter(window.view_3d, _control_event(QEvent.Type.KeyRelease))
    nudge.assert_not_called()


def _start_box_drag(window, view_name):
    obj = window._selected_object()
    view = getattr(window, view_name)
    if view_name == "bev_view":
        view._begin_box_edit(obj, "move", None, obj.box3d.x, obj.box3d.y, 10, 10)
        view._update_edit_preview(obj.box3d.x + 1, obj.box3d.y)
    else:
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        with (
            patch.object(view, "_event_data_point", return_value=QPointF(obj.box3d.x, obj.box3d.z)),
            patch.object(view, "_hit_selected_handle", return_value="move"),
        ):
            view.mousePressEvent(press)
        view._update_edit_preview(obj.box3d.z + 1)
    return view


@pytest.mark.parametrize("view_name", ["bev_view", "side_view"])
def test_frame_switch_discards_previous_frame_drag_without_touching_existing_object(window, view_name):
    window.bev_visible_check.setChecked(True)
    window.side_visible_check.setChecked(True)
    window._create_box(1, 2)
    obj = window._selected_object()
    target = window.importer.import_laser_labels(window.adapter.load_source_frame("000001"))
    existing = replace(obj, box3d=replace(obj.box3d, x=20, z=4))
    window.repository.save(replace(target, objects=(existing,)))
    view = _start_box_drag(window, view_name)

    window._move_frame(1)
    assert window._selected_object() == existing
    assert window.bev_view._move_object is None
    assert window.side_view._edit_object is None
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(40, 10), QPointF(40, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with patch.object(view, "_event_data_point", return_value=QPointF(2, 2)):
        view.mouseReleaseEvent(release)
    assert window._selected_object() == existing
    assert not window.history.dirty


@pytest.mark.parametrize("view_name", ["bev_view", "side_view"])
def test_loading_cancels_drag_and_blocks_new_box_gestures(window, view_name):
    window.bev_visible_check.setChecked(True)
    window.side_visible_check.setChecked(True)
    window._create_box(1, 2)
    view = _start_box_drag(window, view_name)
    with patch.object(window.executor, "submit", return_value=Future()):
        window._move_frame(1)
    assert not view._editing_enabled
    assert window.bev_view._move_object is None
    assert window.side_view._edit_object is None
    before = window.history.current
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with patch.object(view, "_event_data_point") as box_pointer:
        view.mousePressEvent(press)
        box_pointer.assert_not_called()
    assert window.history.current == before
    window._show_load_error(window.request_generation, "000001", "fixture load failed")
    assert view._editing_enabled


def test_frame_switch_cancels_unfinished_create_preview(window):
    window.create_button.setChecked(True)
    view = window.bev_view
    view._drag_start_data = (1, 2)
    view._drag_start_pixel = (10, 10)
    view._update_create_preview(3, 4)
    assert view._create_preview is not None
    window._move_frame(1)
    assert view._drag_start_data is None
    assert view._create_preview is None
    assert not window.history.current.objects


def test_saved_creation_can_be_undone_saved_redone_and_saved_again(window):
    window._create_box(1, 2)
    obj = window._selected_object()
    assert window._save_working_label()
    assert window.history.baseline.revision == 1
    window._undo()
    assert window.history.current.objects == ()
    assert window.history.current.revision == 1
    assert window.history.current.provenance == window.history.baseline.provenance
    assert window.history.dirty
    assert window._save_working_label()
    assert window.repository.load("000000").revision == 2
    assert window.repository.load("000000").objects == ()
    window._redo()
    assert window.history.current.objects == (obj,)
    assert window.history.current.revision == 2
    assert window.history.dirty
    assert window._save_working_label()
    saved = window.repository.load("000000")
    assert saved.revision == 3
    assert saved.objects == (obj,)
    assert not window.history.dirty


def test_undo_after_save_still_rejects_real_external_file_changes(window):
    window._create_box(1, 2)
    assert window._save_working_label()
    path = window.repository.path_for("000000")
    externally_changed = path.read_bytes() + b" "
    path.write_bytes(externally_changed)
    window._undo()
    assert window.history.current.revision == 1
    with patch.object(QMessageBox, "critical") as error:
        assert not window._save_working_label()
    assert "changed since load" in error.call_args.args[2]
    assert path.read_bytes() == externally_changed
    assert window.history.dirty
