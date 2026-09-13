from __future__ import annotations

from dataclasses import replace
import json
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelConflictError, LabelRepository
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.background_task import TaskCancelled, TaskControl
from lidar_label_tool.services.frame_review import (
    FrameReviewEntry,
    next_unreviewed_frame,
    require_re_review,
    scan_frame_review,
    set_frame_review_status,
    visible_review_frame,
)
from tests.unit import test_frame_editing_workflow


window = test_frame_editing_workflow.window


def _label(frame_id="frame_0"):
    return FrameLabel("dataset", frame_id, {"lidar": (f"{frame_id}.bin",)}, {}, "vehicle")


@pytest.mark.parametrize("status", ["reviewed", "skipped", "in_progress", "unvisited"])
def test_explicit_review_command_changes_only_status_and_is_undoable(status):
    label = replace(_label(), extra_fields={"vendor": {"keep": [1]}})
    edited = set_frame_review_status(label, status)
    assert edited == replace(label, frame_status=status)
    history = AnnotationHistory.start(label)
    history.apply(edited)
    assert history.current.frame_status == status
    assert history.undo() == label
    assert history.redo() == edited
    with pytest.raises(ValueError):
        set_frame_review_status(label, "automatic_done")


@pytest.mark.parametrize("status", ["reviewed", "skipped"])
def test_object_edit_requires_review_but_viewing_does_not(status):
    label = replace(_label(), frame_status=status)
    assert require_re_review(label, label) is label
    obj = LabeledObject("object", "car", Box3D(0, 0, 1, 4, 2, 2, 0))
    assert require_re_review(label, replace(label, objects=(obj,))).frame_status == "in_progress"


def test_scan_preserves_order_missing_and_corrupt_labels_and_never_writes(tmp_path):
    repository = LabelRepository.for_sidecar(tmp_path, "dataset")
    repository.save(replace(_label("z"), frame_status="reviewed"))
    repository.save(replace(_label("a"), frame_status="skipped"))
    broken = repository.path_for("broken")
    broken.write_text("{broken", encoding="utf-8")
    originals = {path: path.read_bytes() for path in repository.annotation_dir.iterdir()}
    progress = []
    result = scan_frame_review(repository, ["z", "a", "missing", "broken"], TaskControl(progress.append))
    assert [(item.frame_id, item.status) for item in result.entries] == [
        ("z", "reviewed"), ("a", "skipped"), ("missing", "unvisited"), ("broken", "error"),
    ]
    assert result.entries[-1].error
    assert [(item.completed, item.total) for item in progress] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert {path: path.read_bytes() for path in repository.annotation_dir.iterdir()} == originals


def test_scan_cancels_between_frames_without_partial_result_or_writes(tmp_path):
    repository = LabelRepository.for_sidecar(tmp_path, "dataset")
    control = TaskControl(lambda _: control.cancel())
    with patch.object(repository, "exists", return_value=False) as exists:
        with pytest.raises(TaskCancelled):
            scan_frame_review(repository, ["a", "b", "c"], control)
    assert exists.call_count == 1
    assert not repository.annotation_dir.exists()


def test_next_unreviewed_wraps_once_skips_terminal_and_retains_errors():
    order = ("z", "a", "x", "b")
    entries = {key: FrameReviewEntry(key, value) for key, value in zip(
        order, ("unvisited", "reviewed", "skipped", "error"), strict=True,
    )}
    assert next_unreviewed_frame(order, "z", entries) == "b"
    assert next_unreviewed_frame(order, "b", entries) == "z"
    entries["z"] = FrameReviewEntry("z", "reviewed")
    assert next_unreviewed_frame(order, "b", entries) is None
    assert next_unreviewed_frame(("only",), "only", {}) is None
    assert next_unreviewed_frame(order, "z", {}) == "a"


@pytest.mark.parametrize("filter_name", ["all", "unreviewed", "reviewed", "skipped", "error"])
def test_errors_and_unknown_labels_remain_visible_in_every_filter(filter_name):
    assert visible_review_frame(FrameReviewEntry("bad", "error", "bad JSON"), filter_name)
    assert visible_review_frame(None, filter_name)


def test_gui_review_buttons_save_reload_undo_and_edit_reset(window):
    assert window.history.current.frame_status == "unvisited"
    window.mark_reviewed_button.click()
    assert window.history.current.frame_status == "reviewed"
    assert window.history.dirty
    assert not window.repository.exists("000000")
    assert window._save_working_label()
    saved = json.loads(window.repository.path_for("000000").read_text(encoding="utf-8"))
    assert saved["frame_status"] == "reviewed"
    assert saved["profile_id"] == "aeva_profile"
    window._undo()
    assert window.history.current.frame_status == "unvisited"
    assert window._save_working_label()
    window._redo()
    assert window.history.current.frame_status == "reviewed"
    window._create_box(1, 2)
    assert window.history.current.frame_status == "in_progress"
    window.mark_skipped_button.click()
    assert window.history.current.frame_status == "skipped"
    assert window._save_working_label()
    window._request_frame("000000")
    assert window.history.current.frame_status == "skipped"
    window.reopen_review_button.click()
    assert window.history.current.frame_status == "in_progress"


def _immediate_task(_parent, _title, task):
    return task(TaskControl())


def test_gui_next_unreviewed_skips_reviewed_preserves_saved_order_and_no_carry(window):
    source = window.adapter.load_source_frame("000001")
    window.repository.save(replace(window.importer.import_laser_labels(source), frame_status="reviewed"))
    window._create_box(1, 2)
    with patch("lidar_label_tool.ui.main_window.run_task", side_effect=_immediate_task):
        window.next_unreviewed_button.click()
    assert window.history.current.frame_id == "000002"
    assert window.history.current.objects == ()
    assert window.repository.exists("000000")
    assert tuple(window.frame_combo.itemText(i) for i in range(window.frame_combo.count())) == window.index.frame_ids
    assert "완료 1" in window.review_summary_label.text()


def test_gui_scan_cancel_and_dirty_cancel_preserve_current_label_and_frame(window):
    window._create_box(1, 2)
    original = window.history.current
    window.config["editing"]["autosave_on_frame_change"] = False
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
        with patch("lidar_label_tool.ui.main_window.run_task", side_effect=_immediate_task) as runner:
            window.next_unreviewed_button.click()
    runner.assert_called_once()
    assert window.history.current == original
    with patch("lidar_label_tool.ui.main_window.run_task", return_value=None):
        window.review_refresh_button.click()
    assert window.history.current == original
    assert not window.repository.exists("000000")


def test_gui_scan_rejects_stale_result_and_preserves_external_change_baseline(window):
    window.mark_reviewed_button.click()
    assert window._save_working_label()
    path = window.repository.path_for("000000")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["frame_status"] = "skipped"
    path.write_text(json.dumps(document), encoding="utf-8")
    with patch("lidar_label_tool.ui.main_window.run_task", side_effect=_immediate_task):
        window.review_refresh_button.click()
    with pytest.raises(LabelConflictError):
        window.repository.save(replace(window.history.current, frame_status="in_progress"))

    old_entries = dict(window._review_entries)
    def stale_task(parent, title, task):
        result = _immediate_task(parent, title, task)
        window.request_generation += 1
        return result
    with patch("lidar_label_tool.ui.main_window.run_task", side_effect=stale_task):
        window.review_refresh_button.click()
    assert window._review_entries == old_entries


def test_gui_corrupt_label_is_visible_in_filters_and_next_reports_error(window):
    broken = window.repository.path_for("000001")
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("broken", encoding="utf-8")
    with patch("lidar_label_tool.ui.main_window.run_task", side_effect=_immediate_task):
        window.next_unreviewed_button.click()
    assert window.history.current.frame_id == "000000"
    assert "로드 실패" in window.status_message.text()
    window.review_filter_combo.setCurrentIndex(window.review_filter_combo.findData("reviewed"))
    row = window.frame_combo.findText("000001")
    assert not window.frame_combo.view().isRowHidden(row)
    assert "오류" in window.frame_combo.itemData(row, Qt.ItemDataRole.ToolTipRole)
    assert "오류 1" in window.review_summary_label.text()
    assert broken.read_text(encoding="utf-8") == "broken"


def test_gui_scan_uses_only_selected_profile_and_detects_context_change(window):
    window.mark_reviewed_button.click()
    assert window._save_working_label()
    # Another profile's unrelated same frame ID must not affect this session.
    other = window.repository.annotation_dir.parent.parent / "other_profile" / "aeva" / "000001.json"
    other.parent.mkdir(parents=True)
    other.write_text("broken other profile", encoding="utf-8")
    manifest_path = window.dataset_root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["display_name"] = "changed name requires provenance acknowledgement"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    fresh_adapter = open_dataset_adapter(window.dataset_root, profile_id="aeva_profile")
    fresh_reader = open_label_repository(fresh_adapter)
    before = window.repository.path_for("000000").read_bytes()
    scan = scan_frame_review(fresh_reader, window.index.frame_ids, source_reader=fresh_adapter.load_source_frame)
    assert scan.entries[0].status == "in_progress"
    assert scan.entries[0].needs_review
    assert scan.entries[1].status == "unvisited"
    assert window.repository.path_for("000000").read_bytes() == before
    assert other.read_text(encoding="utf-8") == "broken other profile"


def test_real_background_scan_completes_with_gui_thread_and_no_writes(window):
    window.review_refresh_button.click()
    assert len(window._review_entries) == 3
    assert not window.repository.annotation_dir.exists()


def test_next_unreviewed_discard_prompts_only_once_and_preserves_original_file(window):
    window._create_box(1, 2)
    window.config["editing"]["autosave_on_frame_change"] = False
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as question:
        with patch("lidar_label_tool.ui.main_window.run_task", side_effect=_immediate_task):
            window.next_unreviewed_button.click()
    question.assert_called_once()
    assert window.history.current.frame_id == "000001"
    assert not window.repository.exists("000000")


def test_repeated_box_edit_does_not_rebuild_full_review_index(window):
    window._create_box(1, 2)
    with patch.object(window.frame_combo, "setItemData") as update:
        window._nudge_selected("z", 1)
        window._nudge_selected("z", -1)
    update.assert_not_called()
