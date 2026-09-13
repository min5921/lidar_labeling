from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import fit_box_to_local_ground
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


def test_z_adjustment_can_be_disabled():
    request, target, clouds = scene(shift=(1.1, -0.5, 0))
    request = replace(request, options=TrackingOptions(adjust_z=False))
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
    assert fitted.z == pytest.approx(0.95, abs=0.03)
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
