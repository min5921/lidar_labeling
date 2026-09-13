from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import fit_box_bottom_to_points, fit_box_to_local_ground
from lidar_label_tool.services.object_tracking import (
    TrackingOptions,
    TrackingRequest,
    TrackingResult,
    apply_tracking_result,
    track_object,
)


def cloud(xyz):
    return PointCloudData(
        np.asarray(xyz, dtype=np.float32), {}, "aeva", "1", "lidar:aeva", Path("points.bin")
    )


def scene(*, sign=False, shift=(1.1, -0.5, 0.18), ground=False):
    rng = np.random.default_rng(8)
    box = Box3D(
        10, 2, 3.5 if sign else 0.8, 2 if sign else 4, 0.25 if sign else 2, 1 if sign else 1.6, 0
    )
    points = rng.uniform(-0.45, 0.45, (550, 3)) * [box.length, box.width, box.height]
    points += [box.x, box.y, box.z]
    obj = LabeledObject("track", "sign" if sign else "car", box, source={"raw": {"id": "track"}})
    moved = points + shift
    before, after = points, moved
    if ground:
        gx, gy = np.meshgrid(np.arange(4, 18, 0.25), np.arange(-3, 7, 0.25))
        road = np.column_stack((gx.ravel(), gy.ravel(), np.zeros(gx.size)))
        before = np.vstack((before, road))
        after = np.vstack((after, road + [0, 0, shift[2]]))
    request = TrackingRequest(
        "dataset", "000000", "000001", "lidar:aeva", ("aeva",), obj, (cloud(before),)
    )
    target = FrameLabel("dataset", "000001", {"aeva": ("next.bin",)}, {}, "lidar:aeva")
    return request, target, (cloud(after),)


@pytest.mark.parametrize("sign", [False, True])
def test_tracks_translation_and_z_without_changing_size_or_snapping_sign_to_ground(sign):
    request, target, clouds = scene(sign=sign, ground=True)
    original = request.clouds[0].xyz.copy()
    result = track_object(request, target, clouds)
    assert result.status == "matched", result
    np.testing.assert_allclose(
        [result.box.x, result.box.y, result.box.z],
        [request.obj.box3d.x + 1.1, request.obj.box3d.y - 0.5, request.obj.box3d.z + 0.18],
        atol=0.15,
    )
    assert (result.box.length, result.box.width, result.box.height, result.box.yaw) == (
        request.obj.box3d.length,
        request.obj.box3d.width,
        request.obj.box3d.height,
        request.obj.box3d.yaw,
    )
    np.testing.assert_array_equal(request.clouds[0].xyz, original)
    if sign:
        assert result.box.z - result.box.height / 2 > 2.5


@pytest.mark.parametrize("ground_contact", [False, True])
def test_z_adjustment_can_be_disabled(ground_contact):
    request, target, clouds = scene(shift=(1.1, -0.5, 0))
    request = replace(request, options=TrackingOptions(adjust_z=False, ground_contact=ground_contact))
    result = track_object(request, target, clouds)
    assert result.status == "matched", result
    assert result.box.z == request.obj.box3d.z


def test_ground_mode_is_explicit_and_keeps_dimensions():
    request, target, clouds = scene(ground=True)
    request = replace(request, options=TrackingOptions(ground_contact=True))
    result = track_object(request, target, clouds)
    assert result.status == "matched", result
    assert result.ground_applied
    assert result.box.z - result.box.height / 2 == pytest.approx(0.18, abs=0.03)


def test_sparse_missing_or_incompatible_points_do_not_move_box():
    request, target, clouds = scene()
    for bad in ((), (cloud(clouds[0].xyz[:3]),), (replace(clouds[0], source_frame="other"),)):
        result = track_object(request, target, bad)
        assert result.status != "matched"
        assert result.box == request.obj.box3d
    request.cancel.set()
    assert track_object(request, target, clouds).status == "cancelled"


def test_existing_target_label_is_never_automatically_moved():
    request, target, clouds = scene()
    existing = replace(request.obj, box3d=replace(request.obj.box3d, x=50))
    target = replace(target, objects=(existing,))
    assert track_object(request, target, clouds).status == "existing_label"
    assert target.objects == (existing,)


@pytest.mark.parametrize("adjust_z,ground", [(True, False), (False, False), (True, True)])
def test_explicit_retracking_changes_only_existing_position_and_keeps_target_metadata(adjust_z, ground):
    request, target, clouds = scene(ground=ground)
    request = replace(request, options=TrackingOptions(
        retrack_existing=True, adjust_z=adjust_z, ground_contact=ground,
    ))
    existing = replace(
        request.obj, box3d=replace(request.obj.box3d, x=50, z=1.2, height=1.8, yaw=.2),
        attributes={"occluded": True}, source={"raw": {"target": True}},
        extra_fields={"keep": {"target": [1]}, "tracking_history": [{"method": "vendor"}]},
    )
    other = replace(existing, id="other", box3d=replace(existing.box3d, x=80))
    target = replace(target, objects=(existing, other), frame_status="in_progress")
    result = track_object(request, target, clouds)
    assert result.status == "matched", result
    assert result.expected_target_object == existing
    assert result.expected_target_object is not existing
    assert result.box.x == pytest.approx(request.obj.box3d.x + 1.1, abs=.15)
    assert result.box.y == pytest.approx(request.obj.box3d.y - .5, abs=.15)
    assert replace(result.box, x=existing.box3d.x, y=existing.box3d.y, z=existing.box3d.z) == existing.box3d
    if not adjust_z:
        assert result.box.z == existing.box3d.z
    elif ground:
        assert result.ground_applied
        assert fit_box_bottom_to_points(result.box, clouds) == result.box
    else:
        assert result.box.z == pytest.approx(request.obj.box3d.z + .18, abs=.15)
    assert apply_tracking_result(target, result) is target  # A result alone grants no overwrite.
    edited = apply_tracking_result(target, result, retrack_existing=True)
    assert edited.objects[1] == other
    assert edited.objects[0].box3d == result.box
    assert edited.objects[0].attributes == existing.attributes
    assert edited.objects[0].source == existing.source
    assert edited.objects[0].extra_fields["keep"] == existing.extra_fields["keep"]
    assert edited.objects[0].extra_fields["tracking_history"][0] == {"method": "vendor"}
    assert edited.objects[0].extra_fields["tracking_history"][-1]["retracked_existing"] is True
    assert target.objects == (existing, other)


@pytest.mark.parametrize("status", ["reviewed", "skipped"])
def test_retracking_never_overwrites_completed_frames(status):
    request, target, clouds = scene()
    request = replace(request, options=TrackingOptions(retrack_existing=True))
    target = replace(target, objects=(request.obj,), frame_status=status)
    result = track_object(request, target, clouds)
    assert result.status == "protected_label"
    assert apply_tracking_result(target, result, retrack_existing=True) is target


@pytest.mark.parametrize("change", ["class", "history", "no_points"])
def test_retracking_rejects_mismatched_or_uncertain_existing_object(change):
    request, target, clouds = scene()
    request = replace(request, options=TrackingOptions(retrack_existing=True))
    obj = replace(request.obj, box3d=replace(request.obj.box3d, x=50))
    if change == "class":
        obj = replace(obj, class_name="sign")
    elif change == "history":
        obj = replace(obj, extra_fields={"tracking_history": {"malformed": True}})
    else:
        clouds = ()
    target = replace(target, objects=(obj,))
    result = track_object(request, target, clouds)
    assert result.status != "matched"
    assert result.box == obj.box3d
    assert apply_tracking_result(target, result, retrack_existing=True) is target


@pytest.mark.parametrize("change", ["box", "metadata", "reviewed", "skipped"])
def test_retracking_result_is_discarded_if_target_changed_since_computation(change):
    request, target, clouds = scene()
    request = replace(request, options=TrackingOptions(retrack_existing=True))
    target = replace(target, objects=(request.obj,))
    result = track_object(request, target, clouds)
    assert result.status == "matched"
    if change in {"reviewed", "skipped"}:
        target = replace(target, frame_status=change)
    elif change == "box":
        target = replace(target, objects=(replace(request.obj, box3d=replace(request.obj.box3d, x=30)),))
    else:
        target = replace(target, objects=(replace(request.obj, attributes={"edited": True}),))
    assert apply_tracking_result(target, result, retrack_existing=True) is target


def test_two_identical_candidates_are_ambiguous():
    request, target, clouds = scene(sign=True, shift=(-1.5, 0, 0))
    other = request.clouds[0].xyz + [1.5, 0, 0]
    result = track_object(request, target, (cloud(np.vstack((clouds[0].xyz, other))),))
    assert result.status == "ambiguous", result
    assert result.box == request.obj.box3d


def test_local_ground_requires_supported_nearby_plane():
    box = Box3D(0, 0, 0.8, 4, 2, 1.6, 0)
    x, y = np.meshgrid(np.arange(-2.5, 2.6, 0.25), np.arange(-1.5, 1.6, 0.25))
    points = np.column_stack((x.ravel(), y.ravel(), 0.1 * x.ravel() + 0.15))
    fitted = fit_box_to_local_ground(box, (cloud(points),))
    assert fitted is not None
    assert fitted == fit_box_bottom_to_points(box, (cloud(points),))
    assert fitted.height == box.height
    assert fit_box_to_local_ground(box, (cloud(points[:3]),)) is None
    assert fit_box_to_local_ground(box, (cloud(points + [0, 0, 4]),)) is None
    on_object = (np.abs(points[:, 0]) < 1.9) & (np.abs(points[:, 1]) < 0.9)
    assert fit_box_to_local_ground(box, (cloud(points[on_object]),)) is None


def test_ground_without_supported_plane_keeps_prior_z_while_xy_can_move():
    request, target, clouds = scene(sign=True)
    request = replace(request, options=TrackingOptions(ground_contact=True))
    result = track_object(request, target, clouds)
    assert result.status == "matched", result
    assert result.box.x == pytest.approx(request.obj.box3d.x + 1.1, abs=0.15)
    assert result.box.z == request.obj.box3d.z
    assert not result.ground_applied


def test_tracking_record_is_bounded_and_unknown_metadata_round_trips():
    request, target, _ = scene()
    old = {"method": "local_point_translation", "target_frame_id": "000000"}
    unknown = {"method": "vendor", "payload": {"keep": True}}
    obj = replace(request.obj, extra_fields={"tracking_history": [unknown, old], "other": 42})
    label = replace(target, objects=(obj,))
    result = TrackingResult(
        obj.id, "000000", "000001", replace(obj.box3d, x=11), "matched", "test", 0.9
    )
    edited = apply_tracking_result(label, result)
    assert len(edited.objects[0].extra_fields["tracking_history"]) == 2
    assert edited.objects[0].extra_fields["tracking_history"][0] == unknown
    assert edited.objects[0].extra_fields["other"] == 42
    assert obj.extra_fields["tracking_history"] == [unknown, old]
    assert edited.revision == target.revision
    assert edited.point_cloud_paths == target.point_cloud_paths
    assert apply_tracking_result(label, replace(result, status="ambiguous")) is label


@pytest.mark.parametrize("shift", [(8, 0, 0), (0, 0, 3)])
def test_points_moving_far_outside_search_range_do_not_drag_box(shift):
    request, target, clouds = scene(sign=True, shift=shift)
    result = track_object(request, target, clouds)
    assert result.status != "matched"
    assert result.box == request.obj.box3d
