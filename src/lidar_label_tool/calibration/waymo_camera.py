from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.geometry.box3d import box_corners_3d
from lidar_label_tool.geometry.transforms import invert_transform, validate_rigid_transform


_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


@dataclass(frozen=True, slots=True)
class CameraCalibration:
    camera_id: str
    intrinsic: tuple[float, ...]
    t_vehicle_camera: NDArray[np.float64]
    width: int
    height: int

    def __post_init__(self) -> None:
        if len(self.intrinsic) != 9:
            raise ValueError("Waymo camera intrinsic must contain 9 values")
        validate_rigid_transform(self.t_vehicle_camera)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera image size must be positive")

    @classmethod
    def from_waymo(cls, data: Mapping[str, Any]) -> CameraCalibration:
        return cls(
            camera_id=str(data["name"]),
            intrinsic=tuple(float(value) for value in data["intrinsic"]),
            t_vehicle_camera=np.asarray(
                data["extrinsic"]["transform"], dtype=np.float64
            ).reshape(4, 4),
            width=int(data["width"]),
            height=int(data["height"]),
        )

    @classmethod
    def from_generic(
        cls, camera_id: str, data: Mapping[str, Any]
    ) -> CameraCalibration:
        model = str(data.get("distortion_model", "none"))
        if model == "fisheye":
            raise ValueError("fisheye camera projection is not implemented")
        matrix = np.asarray(data["intrinsic"], dtype=np.float64)
        if matrix.shape != (3, 3):
            raise ValueError("camera intrinsic must have shape [3, 3]")
        coefficients = [float(value) for value in data.get("distortion_coefficients", [])]
        coefficients = (coefficients + [0.0] * 5)[:5]
        if model == "none":
            coefficients = [0.0] * 5
        k1, k2, p1, p2, k3 = coefficients
        width, height = (int(value) for value in data["image_size"])
        t_camera_reference = np.asarray(
            data["T_camera_reference"], dtype=np.float64
        )
        return cls(
            camera_id=camera_id,
            intrinsic=(
                float(matrix[0, 0]),
                float(matrix[1, 1]),
                float(matrix[0, 2]),
                float(matrix[1, 2]),
                k1,
                k2,
                p1,
                p2,
                k3,
            ),
            t_vehicle_camera=invert_transform(t_camera_reference),
            width=width,
            height=height,
        )

    def project_vehicle_points(
        self, points_vehicle: NDArray[np.float64], near_plane: float = 0.1
    ) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
        camera = self.vehicle_to_camera(points_vehicle)
        uv = self.project_camera_points(camera)
        depth = camera[:, 0]
        valid = depth > near_plane
        finite = np.isfinite(uv).all(axis=1)
        reasonable = (
            (np.abs(uv[:, 0]) < self.width * 4.0)
            & (np.abs(uv[:, 1]) < self.height * 4.0)
        )
        return uv, valid & finite & reasonable

    def vehicle_to_camera(
        self, points_vehicle: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        points = np.asarray(points_vehicle, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("points_vehicle must have shape [N, 3]")
        points_h = np.column_stack((points, np.ones(len(points))))
        return (points_h @ invert_transform(self.t_vehicle_camera).T)[:, :3]

    def project_camera_points(
        self, points_camera: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        camera = np.asarray(points_camera, dtype=np.float64)
        if camera.ndim != 2 or camera.shape[1] != 3:
            raise ValueError("points_camera must have shape [N, 3]")
        depth = camera[:, 0]
        safe_depth = np.where(np.abs(depth) > 1e-12, depth, np.nan)
        x = -camera[:, 1] / safe_depth
        y = -camera[:, 2] / safe_depth
        fu, fv, cu, cv, k1, k2, p1, p2, k3 = self.intrinsic
        radius2 = x * x + y * y
        radial = 1.0 + k1 * radius2 + k2 * radius2**2 + k3 * radius2**3
        distorted_x = x * radial + 2.0 * p1 * x * y + p2 * (radius2 + 2.0 * x * x)
        distorted_y = y * radial + p1 * (radius2 + 2.0 * y * y) + 2.0 * p2 * x * y
        return np.column_stack((fu * distorted_x + cu, fv * distorted_y + cv))

    def project_camera_points_undistorted(
        self, points_camera: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        camera = np.asarray(points_camera, dtype=np.float64)
        if camera.ndim != 2 or camera.shape[1] != 3:
            raise ValueError("points_camera must have shape [N, 3]")
        depth = camera[:, 0]
        safe_depth = np.where(np.abs(depth) > 1e-12, depth, np.nan)
        normalized_x = -camera[:, 1] / safe_depth
        normalized_y = -camera[:, 2] / safe_depth
        fu, fv, cu, cv = self.intrinsic[:4]
        return np.column_stack(
            (fu * normalized_x + cu, fv * normalized_y + cv)
        )


@dataclass(frozen=True, slots=True)
class ProjectedWireframe:
    object_id: str
    segments: NDArray[np.float64]

    @property
    def bounds(self) -> tuple[float, float, float, float] | None:
        if self.segments.size == 0:
            return None
        points = self.segments.reshape(-1, 2)
        minimum = points.min(axis=0)
        maximum = points.max(axis=0)
        return (float(minimum[0]), float(minimum[1]), float(maximum[0]), float(maximum[1]))


def project_box_wireframe(
    object_id: str,
    box: Box3D,
    calibration: CameraCalibration,
    *,
    near_plane: float = 0.1,
) -> ProjectedWireframe:
    center_camera = calibration.vehicle_to_camera(
        np.array([[box.x, box.y, box.z]], dtype=np.float64)
    )
    center_uv = calibration.project_camera_points_undistorted(center_camera)
    margin_x = calibration.width * 0.25
    margin_y = calibration.height * 0.25
    center_visible = (
        center_camera[0, 0] > near_plane
        and np.isfinite(center_uv[0]).all()
        and -margin_x <= center_uv[0, 0] <= calibration.width - 1.0 + margin_x
        and -margin_y <= center_uv[0, 1] <= calibration.height - 1.0 + margin_y
    )
    if not center_visible:
        return ProjectedWireframe(
            object_id=object_id, segments=np.empty((0, 2, 2), dtype=np.float64)
        )
    corners = box_corners_3d(box)
    camera_corners = calibration.vehicle_to_camera(corners)
    segments: list[NDArray[np.float64]] = []
    for start, end in _BOX_EDGES:
        clipped_camera = _clip_to_camera_frustum(
            camera_corners[start], camera_corners[end], calibration, near_plane
        )
        if clipped_camera is None:
            continue
        uv = calibration.project_camera_points(clipped_camera)
        if not np.isfinite(uv).all():
            continue
        clipped_image = _clip_to_image(uv[0], uv[1], calibration.width, calibration.height)
        if clipped_image is not None:
            segments.append(clipped_image)
    array = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 2)
    return ProjectedWireframe(object_id=object_id, segments=array)


def camera_synced_projection_box(obj: LabeledObject) -> Box3D:
    """Apply edits made to a LiDAR-time box to its Waymo camera-synced box."""
    raw = obj.source.get("raw")
    if not isinstance(raw, Mapping):
        return obj.box3d
    source = raw.get("box")
    synced = raw.get("camera_synced_box")
    required = {"center_x", "center_y", "center_z", "length", "width", "height"}
    if not isinstance(source, Mapping) or not isinstance(synced, Mapping):
        return obj.box3d
    if not required.issubset(source) or not required.issubset(synced):
        return obj.box3d
    try:
        source_yaw = float(source.get("heading", 0.0))
        synced_yaw = float(synced.get("heading", source_yaw))
        return Box3D(
            x=float(synced["center_x"]) + obj.box3d.x - float(source["center_x"]),
            y=float(synced["center_y"]) + obj.box3d.y - float(source["center_y"]),
            z=float(synced["center_z"]) + obj.box3d.z - float(source["center_z"]),
            length=max(
                0.01,
                float(synced["length"]) + obj.box3d.length - float(source["length"]),
            ),
            width=max(
                0.01,
                float(synced["width"]) + obj.box3d.width - float(source["width"]),
            ),
            height=max(
                0.01,
                float(synced["height"]) + obj.box3d.height - float(source["height"]),
            ),
            yaw=synced_yaw + obj.box3d.yaw - source_yaw,
        )
    except (TypeError, ValueError):
        return obj.box3d


def _clip_to_near_plane(
    start: NDArray[np.float64], end: NDArray[np.float64], near_plane: float
) -> NDArray[np.float64] | None:
    start_depth = float(start[0])
    end_depth = float(end[0])
    if start_depth < near_plane and end_depth < near_plane:
        return None
    clipped_start = start.copy()
    clipped_end = end.copy()
    if start_depth < near_plane:
        ratio = (near_plane - start_depth) / (end_depth - start_depth)
        clipped_start = start + ratio * (end - start)
    elif end_depth < near_plane:
        ratio = (near_plane - end_depth) / (start_depth - end_depth)
        clipped_end = end + ratio * (start - end)
    return np.vstack((clipped_start, clipped_end))


def _clip_to_camera_frustum(
    start: NDArray[np.float64],
    end: NDArray[np.float64],
    calibration: CameraCalibration,
    near_plane: float,
) -> NDArray[np.float64] | None:
    """Clip a camera-space segment before applying the distortion polynomial."""
    fu, fv, cu, cv = calibration.intrinsic[:4]
    normalized_x_min = -cu / fu
    normalized_x_max = (calibration.width - 1.0 - cu) / fu
    normalized_y_min = -cv / fv
    normalized_y_max = (calibration.height - 1.0 - cv) / fv
    planes = (
        (np.array([1.0, 0.0, 0.0]), -near_plane),
        (np.array([-normalized_x_min, -1.0, 0.0]), 0.0),
        (np.array([normalized_x_max, 1.0, 0.0]), 0.0),
        (np.array([-normalized_y_min, 0.0, -1.0]), 0.0),
        (np.array([normalized_y_max, 0.0, 1.0]), 0.0),
    )
    direction = end - start
    lower, upper = 0.0, 1.0
    for normal, offset in planes:
        initial = float(normal @ start + offset)
        change = float(normal @ direction)
        if abs(change) < 1e-12:
            if initial < 0.0:
                return None
            continue
        crossing = -initial / change
        if change > 0.0:
            lower = max(lower, crossing)
        else:
            upper = min(upper, crossing)
        if lower > upper:
            return None
    return np.vstack((start + lower * direction, start + upper * direction))


def _clip_to_image(
    start: NDArray[np.float64], end: NDArray[np.float64], width: int, height: int
) -> NDArray[np.float64] | None:
    """Liang-Barsky clip of a 2D segment to the image rectangle."""
    x0, y0 = float(start[0]), float(start[1])
    dx, dy = float(end[0] - start[0]), float(end[1] - start[1])
    lower, upper = 0.0, 1.0
    for direction, distance in (
        (-dx, x0),
        (dx, width - 1.0 - x0),
        (-dy, y0),
        (dy, height - 1.0 - y0),
    ):
        if abs(direction) < 1e-12:
            if distance < 0.0:
                return None
            continue
        ratio = distance / direction
        if direction < 0.0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return None
    return np.array(
        [[x0 + lower * dx, y0 + lower * dy], [x0 + upper * dx, y0 + upper * dy]],
        dtype=np.float64,
    )
