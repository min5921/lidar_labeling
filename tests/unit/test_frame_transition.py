from __future__ import annotations

from dataclasses import replace

import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.frame_transition import ForwardCarryState
from lidar_label_tool.services.object_tracking import TrackingOptions, TrackingResult


def _source():
    obj = LabeledObject(
        "object", "car", Box3D(1, 2, 1, 4, 2, 2, 0),
        source={"created_by": "lidar_label_tool", "unknown": [1]},
    )
    label = FrameLabel("dataset", "first", {"lidar": ("first.bin",)}, {}, "vehicle", (obj,))
    return label, obj


def test_transition_owns_cancel_and_object_snapshot_without_copying_clouds():
    source, obj = _source()
    state = ForwardCarryState()
    state.ground_object_ids.add(obj.id)
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions())
    request = state.tracking
    assert request is not None
    assert request.obj is not obj
    assert request.obj.source is not obj.source
    state.prepare(source, "later", obj, obj.id, (), None)
    assert request.cancel.is_set()
    assert state.tracking is None
    assert state.target_frame_id == "later"
    state.clear()
    assert state.target_frame_id is None
    assert state.objects == ()
    assert state.ground_object_ids == {obj.id}


@pytest.mark.parametrize("tracking", [False, True])
def test_tracking_carries_only_selected_object_while_plain_carry_keeps_bulk_mode(tracking):
    source, obj = _source()
    transferred = replace(
        obj, id="other-imported", source={"raw": {"id": "other-imported"}},
        extra_fields={"object_transfer_history": [{"operation": "dataset_transfer"}]},
    )
    another_created = replace(obj, id="other-created")
    source = replace(source, objects=(obj, transferred, another_created), frame_status="reviewed")
    state = ForwardCarryState()
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions() if tracking else None)
    assert tuple(item.id for item in state.objects) == (
        (obj.id,) if tracking else (obj.id, transferred.id, another_created.id)
    )
    target = replace(source, frame_id="next", objects=())
    history = AnnotationHistory.start(target)
    outcome = state.apply(history, None, enabled=True, recovered=False)
    assert outcome.object_ids == tuple(item.id for item in state.objects)
    assert history.current.objects == state.objects
    assert source.objects == (obj, transferred, another_created)


def test_tracking_without_selection_does_not_fall_back_to_copying_every_object():
    source, _ = _source()
    state = ForwardCarryState()
    state.prepare(source, "next", None, None, (), TrackingOptions())
    assert state.objects == ()
    assert state.tracking is None
    history = AnnotationHistory.start(replace(source, frame_id="next", objects=()))
    assert not state.apply(history, None, enabled=True, recovered=False).object_ids
    assert not history.dirty


def test_tracking_uses_second_undo_and_never_marks_reviewed():
    source, obj = _source()
    target = replace(source, frame_id="next", objects=(), frame_status="reviewed")
    state = ForwardCarryState()
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions())
    history = AnnotationHistory.start(target)
    result = TrackingResult(obj.id, "first", "next", replace(obj.box3d, x=2), "matched", "추적됨", score=.9)
    outcome = state.apply(history, result, enabled=True, recovered=False)
    assert outcome.object_ids == (obj.id,)
    assert outcome.selected_id == obj.id
    assert history.current.objects[0].box3d.x == 2
    assert history.current.frame_status == "in_progress"
    assert history.undo().objects[0].box3d == obj.box3d
    assert history.undo() == target


def test_recovery_existing_ids_and_wrong_frame_take_precedence():
    source, obj = _source()
    state = ForwardCarryState()
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions())
    recovered = AnnotationHistory.start(replace(source, frame_id="next", objects=()))
    assert not state.apply(recovered, None, enabled=True, recovered=True).object_ids
    assert not recovered.dirty
    unrelated = AnnotationHistory.start(replace(source, frame_id="unrelated", objects=()))
    assert not state.apply(unrelated, None, enabled=True, recovered=False).object_ids
    assert not unrelated.dirty
    existing = AnnotationHistory.start(replace(source, frame_id="next"))
    result = TrackingResult(obj.id, "first", "next", replace(obj.box3d, x=10), "matched", "추적", score=.9)
    state.apply(existing, result, enabled=True, recovered=False)
    assert not existing.dirty


@pytest.mark.parametrize("recovered,enabled", [(True, True), (False, False)])
def test_retracking_never_overwrites_recovery_or_a_disabled_transition(recovered, enabled):
    source, obj = _source()
    state = ForwardCarryState()
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions(retrack_existing=True))
    target = replace(source, frame_id="next")
    history = AnnotationHistory.start(target)
    result = TrackingResult(
        obj.id, source.frame_id, "next", replace(obj.box3d, x=10), "matched", "재추적", score=.9,
        expected_target_object=obj,
    )
    state.apply(history, result, enabled=enabled, recovered=recovered)
    assert history.current == target
    assert not history.dirty


def test_retracking_requires_an_unchanged_target_snapshot_and_uses_one_undo():
    source, obj = _source()
    state = ForwardCarryState()
    state.prepare(source, "next", obj, obj.id, (), TrackingOptions(retrack_existing=True))
    target = replace(source, frame_id="next")
    history = AnnotationHistory.start(target)
    result = TrackingResult(
        obj.id, source.frame_id, "next", replace(obj.box3d, x=10), "matched", "재추적", score=.9,
        expected_target_object=obj,
    )
    outcome = state.apply(history, result, enabled=True, recovered=False)
    assert outcome.object_ids == ()  # No duplicate/carry step for an existing object.
    assert history.current.objects[0].box3d.x == 10
    assert history.undo() == target
    history = AnnotationHistory.start(replace(target, objects=(replace(obj, attributes={"edited": True}),)))
    outcome = state.apply(history, result, enabled=True, recovered=False)
    assert not history.dirty
    assert "변경되어" in outcome.tracking_message
    history = AnnotationHistory.start(replace(target, objects=()))
    outcome = state.apply(history, result, enabled=True, recovered=False)
    assert not history.dirty  # Do not recreate a target deleted after the snapshot.
    assert history.current.objects == ()
    assert "변경되어" in outcome.tracking_message
