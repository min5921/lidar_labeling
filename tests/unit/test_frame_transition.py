from __future__ import annotations

from dataclasses import replace

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
