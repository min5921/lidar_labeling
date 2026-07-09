from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import numpy as np

from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.domain.point_cloud import PointCloudData


def estimate_floor_z_from_footprint(
    clouds: Iterable[PointCloudData],
    *,
    x: float,
    y: float,
    length: float,
    width: float,
    yaw: float,
    margin_m: float = 0.15,
    percentile: float = 5.0,
    min_points: int = 12,
) -> float | None:
    """Estimate object floor z from points inside an XY footprint.

    Input point clouds must already be in the same reference frame as the box:
    x forward, y left, z up, unit meter. The function reads only render/source
    point arrays and never mutates the original :class:`PointCloudData`.
    """
    if length <= 0 or width <= 0:
        return None
    if not 0.0 <= percentile <= 100.0:
        raise ValueError("percentile must be in [0, 100]")

    cosine = np.cos(yaw)
    sine = np.sin(yaw)
    half_length = length / 2.0 + margin_m
    half_width = width / 2.0 + margin_m
    z_values: list[np.ndarray] = []
    total = 0
    origin = np.array([x, y], dtype=np.float64)

    for cloud in clouds:
        xyz = cloud.xyz.astype(np.float64, copy=False)
        if xyz.size == 0:
            continue
        delta_xy = xyz[:, :2] - origin
        local_x = cosine * delta_xy[:, 0] + sine * delta_xy[:, 1]
        local_y = -sine * delta_xy[:, 0] + cosine * delta_xy[:, 1]
        mask = (np.abs(local_x) <= half_length) & (np.abs(local_y) <= half_width)
        selected_z = xyz[mask, 2]
        if selected_z.size:
            finite_z = selected_z[np.isfinite(selected_z)]
            if finite_z.size:
                z_values.append(finite_z)
                total += int(finite_z.size)

    if total < min_points:
        return None
    return float(np.percentile(np.concatenate(z_values), percentile))


def fit_box_bottom_to_points(
    box: Box3D,
    clouds: Iterable[PointCloudData],
    *,
    margin_m: float = 0.15,
    percentile: float = 5.0,
    min_points: int = 12,
) -> Box3D | None:
    """Return a copy whose bottom face is aligned to the point footprint floor."""
    floor_z = estimate_floor_z_from_footprint(
        clouds,
        x=box.x,
        y=box.y,
        length=box.length,
        width=box.width,
        yaw=box.yaw,
        margin_m=margin_m,
        percentile=percentile,
        min_points=min_points,
    )
    if floor_z is None:
        return None
    return replace(box, z=floor_z + box.height / 2.0)
