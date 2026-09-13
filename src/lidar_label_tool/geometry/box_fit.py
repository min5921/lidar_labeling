from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import numpy as np

from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.point_selection import points_in_box


_FLOOR_MARGIN_M = 0.15
_GROUND_RESIDUAL_M = 0.08


def estimate_floor_z_from_footprint(
    clouds: Iterable[PointCloudData],
    *,
    x: float,
    y: float,
    length: float,
    width: float,
    yaw: float,
    margin_m: float = _FLOOR_MARGIN_M,
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
    margin_m: float = _FLOOR_MARGIN_M,
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


def fit_box_to_local_ground(
    box: Box3D, clouds: Iterable[PointCloudData], *, max_z_step_m: float = 0.6,
) -> Box3D | None:
    """Fit z to the manual point-floor reference after confirming ground support.

    Explicit opt-in for ground-contact objects. Reads [N,3] float32/64 points in
    the box's reference frame (meter, x forward/y left/z up). Size/yaw stay fixed.
    A local plane confirms support; its center height is NOT the final box floor.
    The final z uses fit_box_bottom_to_points, so manual B cannot shift a supported
    result again on the same clouds/footprint. Sparse, steep, inconsistent or
    distant evidence returns None, not a guess. Cloud arrays are never modified.
    """
    if not np.isfinite(max_z_step_m) or max_z_step_m <= 0:
        raise ValueError("max_z_step_m must be positive and finite")
    clouds = tuple(clouds)
    bottom = box.z - box.height / 2
    search = replace(box, z=bottom, height=2 * max_z_step_m, length=box.length + 1.5, width=box.width + 1.5)
    parts = [cloud.xyz[points_in_box(cloud.xyz, search)] for cloud in clouds]
    if not parts or sum(len(part) for part in parts) < 18:
        return None
    points = np.concatenate(parts).astype(np.float64)
    points -= np.array([box.x, box.y, bottom])
    # One low observation per XY cell limits dense vertical surfaces and runtime.
    keys = np.floor(points[:, :2] / 0.35).astype(np.int64)
    order = np.argsort(points[:, 2], kind="stable")
    _, indices = np.unique(keys[order], axis=0, return_index=True)
    points = points[order[indices]]
    if len(points) > 400:
        points = points[np.linspace(0, len(points) - 1, 400, dtype=int)]
    if len(points) < 12:
        return None
    design = np.column_stack((points[:, :2], np.ones(len(points))))
    best: np.ndarray = np.zeros(len(points), dtype=bool)
    generator = np.random.default_rng(0)
    for _ in range(64):
        indices = generator.choice(len(points), size=3, replace=False)
        matrix = design[indices]
        if abs(np.linalg.det(matrix)) < 0.05:
            continue
        plane = np.linalg.solve(matrix, points[indices, 2])
        if np.linalg.norm(plane[:2]) > 0.35:
            continue
        inliers = np.abs(design @ plane - points[:, 2]) <= _GROUND_RESIDUAL_M
        if np.count_nonzero(inliers) > np.count_nonzero(best):
            best = inliers
    if np.count_nonzero(best) < max(12, len(points) * 0.5):
        return None
    support = points[best, :2]
    if np.min(np.ptp(support, axis=0)) < 0.5:
        return None
    cosine, sine = np.cos(box.yaw), np.sin(box.yaw)
    outside = (
        (np.abs(cosine * support[:, 0] + sine * support[:, 1]) > box.length / 2 + 0.1)
        | (np.abs(-sine * support[:, 0] + cosine * support[:, 1]) > box.width / 2 + 0.1)
    )
    if np.count_nonzero(outside) < 6:
        return None  # A flat surface on the object itself is not evidence of ground.
    plane, _, rank, _ = np.linalg.lstsq(design[best], points[best, 2], rcond=None)
    if rank < 3 or np.linalg.norm(plane[:2]) > 0.35 or abs(plane[2]) > max_z_step_m:
        return None
    fitted = fit_box_bottom_to_points(box, clouds)
    if fitted is None or abs(fitted.z - box.z) > max_z_step_m:
        return None
    # On slopes the low footprint percentile lies below the plane's center.
    # Allow the plane's height range over the same yaw-oriented footprint, but
    # reject an object underside or another vertical layer as automatic ground.
    slope_x = plane[0] * cosine + plane[1] * sine
    slope_y = -plane[0] * sine + plane[1] * cosine
    height_range = (
        abs(slope_x) * (box.length / 2 + _FLOOR_MARGIN_M)
        + abs(slope_y) * (box.width / 2 + _FLOOR_MARGIN_M)
    )
    if abs(fitted.z - (box.z + plane[2])) > height_range + _GROUND_RESIDUAL_M:
        return None
    return fitted
