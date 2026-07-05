from __future__ import annotations

from dataclasses import replace
import math
from typing import Literal

from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.geometry.box3d import bev_corners


MIN_BOX_SIZE_M = 0.05


def move_box_xy(box: Box3D, delta_x: float, delta_y: float) -> Box3D:
    """Translate a reference-frame box in x-forward/y-left while preserving other fields."""
    return replace(box, x=box.x + delta_x, y=box.y + delta_y)


def resize_box_from_corner(
    box: Box3D,
    corner_index: int,
    x: float,
    y: float,
    *,
    minimum_size: float = MIN_BOX_SIZE_M,
) -> Box3D:
    """Resize in yaw-aligned XY with the opposite corner fixed in reference coordinates."""
    if corner_index not in {0, 1, 2, 3}:
        raise ValueError("corner_index must be in [0, 3]")
    if minimum_size <= 0:
        raise ValueError("minimum_size must be positive")

    opposite = (corner_index + 2) % 4
    fixed_x, fixed_y = bev_corners(box)[opposite]
    delta_x, delta_y = x - fixed_x, y - fixed_y
    cosine = math.cos(box.yaw)
    sine = math.sin(box.yaw)
    along_length = cosine * delta_x + sine * delta_y
    along_width = -sine * delta_x + cosine * delta_y
    length_sign = 1.0 if corner_index in {0, 1} else -1.0
    width_sign = 1.0 if corner_index in {0, 3} else -1.0
    length = max(minimum_size, length_sign * along_length)
    width = max(minimum_size, width_sign * along_width)

    half_length_x = length_sign * length * cosine / 2.0
    half_length_y = length_sign * length * sine / 2.0
    half_width_x = width_sign * width * -sine / 2.0
    half_width_y = width_sign * width * cosine / 2.0
    return replace(
        box,
        x=float(fixed_x + half_length_x + half_width_x),
        y=float(fixed_y + half_length_y + half_width_y),
        length=length,
        width=width,
    )


def rotate_box_toward(box: Box3D, x: float, y: float) -> Box3D:
    """Set yaw so the box length/front axis points from its center toward XY."""
    if math.isclose(x, box.x, abs_tol=1e-12) and math.isclose(
        y, box.y, abs_tol=1e-12
    ):
        return box
    return replace(box, yaw=math.atan2(y - box.y, x - box.x))


def move_box_z(box: Box3D, delta_z: float) -> Box3D:
    """Translate a box only along reference-frame z-up."""
    return replace(box, z=box.z + delta_z)


def resize_box_height(
    box: Box3D,
    edge: Literal["top", "bottom"],
    z: float,
    *,
    minimum_size: float = MIN_BOX_SIZE_M,
) -> Box3D:
    """Resize height with the opposite horizontal face fixed in reference z-up."""
    if minimum_size <= 0:
        raise ValueError("minimum_size must be positive")
    bottom = box.z - box.height / 2.0
    top = box.z + box.height / 2.0
    if edge == "top":
        new_top = max(z, bottom + minimum_size)
        return replace(
            box,
            z=(bottom + new_top) / 2.0,
            height=new_top - bottom,
        )
    if edge == "bottom":
        new_bottom = min(z, top - minimum_size)
        return replace(
            box,
            z=(new_bottom + top) / 2.0,
            height=top - new_bottom,
        )
    raise ValueError("edge must be 'top' or 'bottom'")
