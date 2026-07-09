from __future__ import annotations

import numpy as np
import pytest

from lidar_label_tool.domain.labels import Box3D
from pathlib import Path

from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import (
    estimate_floor_z_from_footprint,
    fit_box_bottom_to_points,
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
