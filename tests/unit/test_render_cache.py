from __future__ import annotations

from pathlib import Path

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.ui.render_cache import PointCloudRenderCache


def _cloud() -> PointCloudData:
    xyz = np.arange(60, dtype=np.float32).reshape(20, 3)
    return PointCloudData(
        xyz=xyz,
        attributes={"intensity": np.linspace(0.0, 1.0, 20, dtype=np.float32)},
        sensor_id="MERGED",
        return_id="first",
        source_frame="vehicle",
        source_path=Path("000001.bin"),
    )


def test_same_render_key_returns_cached_arrays() -> None:
    cloud = _cloud()
    cache = PointCloudRenderCache(max_cache_mb=1)

    first = cache.prepare(
        [cloud], max_points=10, color_mode="sensor", uniform_color="#FFFFFF"
    )
    second = cache.prepare(
        [cloud], max_points=10, color_mode="sensor", uniform_color="#FFFFFF"
    )

    assert first.clouds[0] is second.clouds[0]
    assert first.rendered_point_count == 10


def test_color_mode_and_max_points_invalidate_cache() -> None:
    cloud = _cloud()
    cache = PointCloudRenderCache(max_cache_mb=1)
    baseline = cache.prepare(
        [cloud], max_points=20, color_mode="sensor", uniform_color="#FFFFFF"
    )
    recolored = cache.prepare(
        [cloud], max_points=20, color_mode="height", uniform_color="#FFFFFF"
    )
    downsampled = cache.prepare(
        [cloud], max_points=5, color_mode="sensor", uniform_color="#FFFFFF"
    )

    assert recolored.clouds[0] is not baseline.clouds[0]
    assert downsampled.clouds[0] is not baseline.clouds[0]
    assert downsampled.rendered_point_count == 5


def test_render_arrays_do_not_modify_or_share_source_xyz() -> None:
    cloud = _cloud()
    original = cloud.xyz.copy()
    cache = PointCloudRenderCache(max_cache_mb=1)

    result = cache.prepare(
        [cloud], max_points=7, color_mode="intensity", uniform_color="#FFFFFF"
    )

    np.testing.assert_array_equal(cloud.xyz, original)
    assert not np.shares_memory(result.clouds[0].xyz, cloud.xyz)
    assert not result.clouds[0].xyz.flags.writeable
    assert not result.clouds[0].rgba.flags.writeable
