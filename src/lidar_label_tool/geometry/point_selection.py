from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.domain.labels import Box3D


def points_in_box(xyz: np.ndarray, box: Box3D, *, margin_m: float = 0.0) -> NDArray[np.bool_]:
    """Mask finite [N,3] float32/64 points inside a yaw-oriented box, including faces.

    Points and box share a reference frame: meter, x forward, y left, z up,
    yaw radians around +z. Input arrays are read only; no coordinates are changed.
    """
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("xyz must have shape [N, 3]")
    if not np.isfinite(margin_m) or margin_m < 0:
        raise ValueError("margin_m must be finite and non-negative")
    dx, dy = xyz[:, 0] - box.x, xyz[:, 1] - box.y
    cosine, sine = np.cos(box.yaw), np.sin(box.yaw)
    return (
        np.isfinite(xyz).all(axis=1)
        & (np.abs(cosine * dx + sine * dy) <= box.length / 2 + margin_m)
        & (np.abs(-sine * dx + cosine * dy) <= box.width / 2 + margin_m)
        & (np.abs(xyz[:, 2] - box.z) <= box.height / 2 + margin_m)
    )
