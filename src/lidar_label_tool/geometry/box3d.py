from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.domain.labels import Box3D


def _rotation_z(yaw: float) -> NDArray[np.float64]:
    cosine = np.cos(yaw)
    sine = np.sin(yaw)
    return np.array([[cosine, -sine], [sine, cosine]], dtype=np.float64)


def bev_corners(box: Box3D) -> NDArray[np.float64]:
    """Return clockwise XY corners starting at local front-left."""
    half_length = box.length / 2.0
    half_width = box.width / 2.0
    local = np.array(
        [
            [half_length, half_width],
            [half_length, -half_width],
            [-half_length, -half_width],
            [-half_length, half_width],
        ],
        dtype=np.float64,
    )
    return local @ _rotation_z(box.yaw).T + np.array([box.x, box.y])


def box_contains_xy(box: Box3D, x: float, y: float) -> bool:
    """Return whether reference-frame XY point [x forward, y left] is inside box."""
    cosine = math.cos(box.yaw)
    sine = math.sin(box.yaw)
    dx, dy = x - box.x, y - box.y
    local_x = cosine * dx + sine * dy
    local_y = -sine * dx + cosine * dy
    return abs(local_x) <= box.length / 2.0 and abs(local_y) <= box.width / 2.0


def box_corners_3d(box: Box3D) -> NDArray[np.float64]:
    """Return 8 corners: bottom four followed by top four."""
    xy = bev_corners(box)
    bottom = np.column_stack((xy, np.full(4, box.z - box.height / 2.0)))
    top = np.column_stack((xy, np.full(4, box.z + box.height / 2.0)))
    return np.vstack((bottom, top))


def side_rectangle(box: Box3D, plane: str = "xz") -> NDArray[np.float64]:
    """Return an axis-aligned side-view rectangle [min_u,min_z,max_u,max_z]."""
    if plane not in {"xz", "yz"}:
        raise ValueError("plane must be 'xz' or 'yz'")
    xy = bev_corners(box)
    axis = 0 if plane == "xz" else 1
    return np.array(
        [
            float(xy[:, axis].min()),
            box.z - box.height / 2.0,
            float(xy[:, axis].max()),
            box.z + box.height / 2.0,
        ],
        dtype=np.float64,
    )
