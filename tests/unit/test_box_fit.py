from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from lidar_label_tool.domain.labels import Box3D
from pathlib import Path

from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import (
    estimate_floor_z_from_footprint,
    fit_box_bottom_to_points,
    fit_box_to_local_ground,
)


def _cloud(points: list[list[float]]) -> PointCloudData:
    return PointCloudData(
        xyz=np.array(points, dtype=np.float32),
        attributes={},
        sensor_id="MERGED",
        return_id="1",
        source_frame="vehicle",
        source_path=Path("memory.bin"),
    )


def test_estimates_floor_from_points_inside_box_footprint() -> None:
    cloud = _cloud(
        [
            [0.0, 0.0, -0.45],
            [0.2, 0.0, -0.40],
            [0.5, 0.2, 0.30],
            [0.8, -0.2, 0.70],
            [8.0, 8.0, -10.0],
        ]
    )

    floor = estimate_floor_z_from_footprint(
        [cloud],
        x=0.0,
        y=0.0,
        length=2.0,
        width=1.0,
        yaw=0.0,
        percentile=0.0,
        min_points=4,
    )

    assert floor == pytest.approx(-0.45)


def test_fit_box_bottom_to_points_keeps_size_and_sets_center_z() -> None:
    box = Box3D(x=0.0, y=0.0, z=1.0, length=2.0, width=1.0, height=1.6, yaw=0.0)
    fitted = fit_box_bottom_to_points(
        box,
        [_cloud([[0.0, 0.0, -0.2], [0.2, 0.0, 0.2], [0.4, 0.0, 0.8]])],
        percentile=0.0,
        min_points=3,
    )

    assert fitted is not None
    assert fitted.height == box.height
    assert fitted.length == box.length
    assert fitted.width == box.width
    assert fitted.z == pytest.approx(-0.2 + box.height / 2.0)


def test_returns_none_when_footprint_has_too_few_points() -> None:
    box = Box3D(x=0.0, y=0.0, z=1.0, length=2.0, width=1.0, height=1.6, yaw=0.0)

    fitted = fit_box_bottom_to_points(
        box,
        [_cloud([[5.0, 5.0, -0.2], [0.0, 0.0, 0.1]])],
        min_points=2,
    )

    assert fitted is None


def test_original_cloud_array_is_not_modified() -> None:
    cloud = _cloud([[0.0, 0.0, -0.2], [0.2, 0.0, 0.4]])
    original = cloud.xyz.copy()

    estimate_floor_z_from_footprint(
        [cloud], x=0.0, y=0.0, length=2.0, width=1.0, yaw=0.0, min_points=1
    )

    np.testing.assert_array_equal(cloud.xyz, original)


@pytest.mark.parametrize("slope,yaw", [(0.0, 0.0), (0.03, 0.0), (0.1, 0.6), (-0.06, -0.8)])
def test_auto_ground_and_manual_floor_use_the_same_height(slope: float, yaw: float) -> None:
    box = Box3D(0, 0, 0.8, 4, 2, 1.6, yaw)
    x, y = np.meshgrid(np.arange(-3, 3.1, 0.2), np.arange(-2.5, 2.6, 0.2))
    points = np.column_stack((x.ravel(), y.ravel(), slope * x.ravel() + 0.05))
    cloud = _cloud(points.tolist())
    original = cloud.xyz.copy()

    # Generator input must remain available to both support and floor estimators.
    automatic = fit_box_to_local_ground(box, iter((cloud,)))
    manual = fit_box_bottom_to_points(box, (cloud,))

    assert automatic is not None and manual is not None
    assert automatic == manual
    assert fit_box_bottom_to_points(automatic, (cloud,)) == automatic
    assert fit_box_to_local_ground(automatic, (cloud,)) == automatic
    assert replace(automatic, z=box.z) == box
    np.testing.assert_array_equal(cloud.xyz, original)


def test_noisy_ground_does_not_move_down_again_after_manual_floor_fit() -> None:
    x, y = np.meshgrid(np.arange(-3, 3.1, 0.2), np.arange(-2, 2.1, 0.2))
    noise = np.random.default_rng(41).normal(0, 0.018, x.size)
    cloud = _cloud(np.column_stack((x.ravel(), y.ravel(), noise)).tolist())
    box = Box3D(0, 0, 0.8, 4, 2, 1.6, 0)
    fitted = fit_box_to_local_ground(box, (cloud,))
    assert fitted is not None
    assert fit_box_bottom_to_points(fitted, (cloud,)) == fitted


@pytest.mark.parametrize("floor_z", [-0.4, 0.35])
def test_auto_ground_rejects_footprint_floor_inconsistent_with_supported_plane(floor_z: float) -> None:
    box = Box3D(0, 0, 0.8, 4, 2, 1.6, 0)
    x, y = np.meshgrid(np.arange(-3, 3.1, 0.2), np.arange(-2, 2.1, 0.2))
    outside = (np.abs(x.ravel()) > 2.2) | (np.abs(y.ravel()) > 1.2)
    road = np.column_stack((x.ravel()[outside], y.ravel()[outside], np.zeros(outside.sum())))
    ix, iy = np.meshgrid(np.arange(-1.5, 1.6, 0.4), np.arange(-0.8, 0.9, 0.4))
    object_or_other_layer = np.column_stack((ix.ravel(), iy.ravel(), np.full(ix.size, floor_z)))
    cloud = _cloud(np.vstack((road, object_or_other_layer)).tolist())

    # Explicit manual placement is available, but automatic ground mode must not
    # mistake an underside or a different layer for the supported road surface.
    assert fit_box_bottom_to_points(box, (cloud,)).z == pytest.approx(box.z + floor_z)
    assert fit_box_to_local_ground(box, (cloud,)) is None


def test_auto_ground_keeps_z_when_manual_floor_exceeds_step_limit() -> None:
    box = Box3D(0, 0, 0.8, 4, 2, 1.6, 0)
    x, y = np.meshgrid(np.arange(-3, 3.1, 0.2), np.arange(-2, 2.1, 0.2))
    road = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, -0.57)))
    low = np.column_stack((np.linspace(-1, 1, 40), np.zeros(40), np.full(40, -0.63)))
    cloud = _cloud(np.vstack((road, low)).tolist())
    assert fit_box_bottom_to_points(box, (cloud,)).z < box.z - 0.6
    assert fit_box_to_local_ground(box, (cloud,), max_z_step_m=0.6) is None
