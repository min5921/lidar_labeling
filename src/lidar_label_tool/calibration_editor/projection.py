from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.calibration.waymo_camera import CameraCalibration
from lidar_label_tool.domain.point_cloud import PointCloudData


@dataclass(frozen=True, slots=True)
class ProjectionStats:
    sampled_points: int
    points_in_front: int
    finite_points: int
    points_in_image: int


@dataclass(frozen=True, slots=True)
class PointProjection:
    uv: NDArray[np.float32]
    depth_m: NDArray[np.float32]
    stats: ProjectionStats

    def __post_init__(self) -> None:
        if self.uv.ndim != 2 or self.uv.shape[1] != 2:
            raise ValueError("projected uv must have shape [N, 2]")
        if self.depth_m.ndim != 1 or len(self.depth_m) != len(self.uv):
            raise ValueError("projected depth must have shape [N]")


def sample_reference_points(
    clouds: Iterable[PointCloudData],
    *,
    max_points: int,
    reference_frame: str | None = None,
) -> NDArray[np.float32]:
    """Return deterministic render samples with shape ``[N,3]`` in metres.

    Input ``xyz`` arrays are ``float32`` and must already be in the label/reference
    coordinate frame. The full source clouds are never copied; only sampled rows are
    combined when more than one cloud is active.
    """
    if max_points <= 0:
        raise ValueError("max_points must be positive")
    available = tuple(cloud for cloud in clouds if cloud.point_count > 0)
    if reference_frame is not None:
        wrong_frames = sorted(
            {cloud.source_frame for cloud in available if cloud.source_frame != reference_frame}
        )
        if wrong_frames:
            raise ValueError(
                "point clouds are not in the requested reference frame: "
                + ", ".join(wrong_frames)
            )
    total = sum(cloud.point_count for cloud in available)
    if total == 0:
        return np.empty((0, 3), dtype=np.float32)
    stride = max(1, math.ceil(total / max_points))
    sampled = [cloud.xyz[::stride] for cloud in available]
    if len(sampled) == 1:
        return np.ascontiguousarray(sampled[0][:max_points])
    return np.ascontiguousarray(np.concatenate(sampled, axis=0)[:max_points])


def project_reference_points(
    xyz_reference: NDArray[np.float32] | NDArray[np.float64],
    calibration: CameraCalibration,
    *,
    near_plane_m: float = 0.1,
) -> PointProjection:
    """Project ``[N,3]`` reference-frame metres into camera image pixels."""
    points = np.asarray(xyz_reference, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("xyz_reference must have shape [N, 3]")
    if near_plane_m <= 0.0:
        raise ValueError("near_plane_m must be positive")
    if len(points) == 0:
        return PointProjection(
            uv=np.empty((0, 2), dtype=np.float32),
            depth_m=np.empty((0,), dtype=np.float32),
            stats=ProjectionStats(0, 0, 0, 0),
        )
    camera_points = calibration.vehicle_to_camera(points)
    depth = camera_points[:, 0]
    in_front = depth > near_plane_m
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        uv = calibration.project_camera_points(camera_points)
    finite = np.isfinite(uv).all(axis=1) & np.isfinite(depth)
    in_image = (
        in_front
        & finite
        & (uv[:, 0] >= 0.0)
        & (uv[:, 0] < calibration.width)
        & (uv[:, 1] >= 0.0)
        & (uv[:, 1] < calibration.height)
    )
    return PointProjection(
        uv=np.ascontiguousarray(uv[in_image].astype(np.float32, copy=False)),
        depth_m=np.ascontiguousarray(depth[in_image].astype(np.float32, copy=False)),
        stats=ProjectionStats(
            sampled_points=len(points),
            points_in_front=int(np.count_nonzero(in_front)),
            finite_points=int(np.count_nonzero(in_front & finite)),
            points_in_image=int(np.count_nonzero(in_image)),
        ),
    )
