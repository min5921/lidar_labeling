from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.calibration.waymo_camera import CameraCalibration
from lidar_label_tool.geometry.transforms import invert_transform, validate_rigid_transform


_SUPPORTED_DISTORTION_MODELS = {"none", "brown_conrady"}


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """Pinhole intrinsics for an image using pixel coordinates.

    ``fx``, ``fy``, ``cx`` and ``cy`` are pixels. Brown-Conrady coefficients use
    the order ``k1, k2, p1, p2, k3``. Fisheye projection is deliberately rejected
    until the renderer implements the same model.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    distortion_model: str = "none"
    distortion_coefficients: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        values = (self.fx, self.fy, self.cx, self.cy, *self.distortion_coefficients)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("camera intrinsic values must be finite")
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("camera focal lengths must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera image size must be positive")
        if self.distortion_model not in _SUPPORTED_DISTORTION_MODELS:
            raise ValueError(
                f"unsupported distortion model for preview: {self.distortion_model}"
            )
        if len(self.distortion_coefficients) > 5:
            raise ValueError("Brown-Conrady distortion supports at most 5 coefficients")

    @classmethod
    def estimated_for_image(cls, width: int, height: int) -> CameraIntrinsics:
        """Create an explicit rough starting point, not a calibrated intrinsic."""
        focal = float(max(width, height))
        return cls(
            fx=focal,
            fy=focal,
            cx=(float(width) - 1.0) / 2.0,
            cy=(float(height) - 1.0) / 2.0,
            width=width,
            height=height,
        )

    @classmethod
    def from_generic(cls, data: Mapping[str, Any]) -> CameraIntrinsics:
        matrix = np.asarray(data["intrinsic"], dtype=np.float64)
        if matrix.shape != (3, 3):
            raise ValueError("camera intrinsic must have shape [3, 3]")
        width, height = (int(value) for value in data["image_size"])
        model = str(data.get("distortion_model", "none"))
        coefficients = tuple(
            float(value) for value in data.get("distortion_coefficients", ())
        )
        if model == "none":
            coefficients = ()
        return cls(
            fx=float(matrix[0, 0]),
            fy=float(matrix[1, 1]),
            cx=float(matrix[0, 2]),
            cy=float(matrix[1, 2]),
            width=width,
            height=height,
            distortion_model=model,
            distortion_coefficients=coefficients,
        )

    @classmethod
    def from_camera_calibration(
        cls, calibration: CameraCalibration
    ) -> CameraIntrinsics:
        fx, fy, cx, cy, k1, k2, p1, p2, k3 = calibration.intrinsic
        coefficients = (k1, k2, p1, p2, k3)
        model = "brown_conrady" if any(abs(value) > 0.0 for value in coefficients) else "none"
        return cls(
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            width=calibration.width,
            height=calibration.height,
            distortion_model=model,
            distortion_coefficients=coefficients if model != "none" else (),
        )

    def matrix(self) -> list[list[float]]:
        return [
            [self.fx, 0.0, self.cx],
            [0.0, self.fy, self.cy],
            [0.0, 0.0, 1.0],
        ]

    def padded_distortion(self) -> tuple[float, float, float, float, float]:
        values = self.distortion_coefficients + (0.0,) * 5
        return (values[0], values[1], values[2], values[3], values[4])


@dataclass(frozen=True, slots=True)
class PoseDelta:
    """A target-camera-frame correction applied as ``delta @ T_base``.

    Translation is metres. Rotations are degrees and compose as ``Rz @ Ry @ Rx``
    for yaw, pitch and roll around the target camera axes.
    """

    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (
                self.x_m,
                self.y_m,
                self.z_m,
                self.roll_deg,
                self.pitch_deg,
                self.yaw_deg,
            )
        ):
            raise ValueError("pose delta values must be finite")

    @property
    def is_identity(self) -> bool:
        return all(
            abs(value) <= 1e-12
            for value in (
                self.x_m,
                self.y_m,
                self.z_m,
                self.roll_deg,
                self.pitch_deg,
                self.yaw_deg,
            )
        )

    def matrix(self) -> NDArray[np.float64]:
        roll, pitch, yaw = np.radians(
            [self.roll_deg, self.pitch_deg, self.yaw_deg]
        )
        cx, sx = math.cos(roll), math.sin(roll)
        cy, sy = math.cos(pitch), math.sin(pitch)
        cz, sz = math.cos(yaw), math.sin(yaw)
        rotation_x = np.array(
            [[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]],
            dtype=np.float64,
        )
        rotation_y = np.array(
            [[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]],
            dtype=np.float64,
        )
        rotation_z = np.array(
            [[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        transform = np.eye(4, dtype=np.float64)
        transform[:3, :3] = rotation_z @ rotation_y @ rotation_x
        transform[:3, 3] = [self.x_m, self.y_m, self.z_m]
        return transform


@dataclass(frozen=True, slots=True)
class CalibrationDraft:
    """An immutable camera calibration draft independent of Qt and file I/O."""

    camera_id: str
    reference_frame: str
    base_transform: NDArray[np.float64]
    base_intrinsics: CameraIntrinsics
    intrinsics: CameraIntrinsics
    correction: PoseDelta = PoseDelta()
    source_kind: str = "new"
    source_path: Path | None = None
    source_fingerprint: str | None = None
    time_offset_ns: int | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.camera_id or not self.reference_frame:
            raise ValueError("camera_id and reference_frame are required")
        validated = validate_rigid_transform(self.base_transform)
        object.__setattr__(self, "base_transform", validated.copy())

    @classmethod
    def new(
        cls,
        camera_id: str,
        reference_frame: str,
        image_size: tuple[int, int],
    ) -> CalibrationDraft:
        intrinsics = CameraIntrinsics.estimated_for_image(*image_size)
        return cls(
            camera_id=camera_id,
            reference_frame=reference_frame,
            base_transform=np.eye(4, dtype=np.float64),
            base_intrinsics=intrinsics,
            intrinsics=intrinsics,
        )

    @classmethod
    def from_generic(
        cls,
        camera_id: str,
        reference_frame: str,
        data: Mapping[str, Any],
        *,
        source_path: Path | None,
        source_fingerprint: str | None,
    ) -> CalibrationDraft:
        raw_base = validate_rigid_transform(data["T_camera_reference"])
        raw_correction = validate_rigid_transform(
            data.get("correction_delta", np.eye(4, dtype=np.float64))
        )
        # Flatten an existing correction into the immutable baseline. New editor
        # changes then start at zero while preserving the exact active projection.
        base_transform = raw_correction @ raw_base
        intrinsics = CameraIntrinsics.from_generic(data)
        return cls(
            camera_id=camera_id,
            reference_frame=reference_frame,
            base_transform=base_transform,
            base_intrinsics=intrinsics,
            intrinsics=intrinsics,
            source_kind="generic",
            source_path=source_path,
            source_fingerprint=source_fingerprint,
            time_offset_ns=(
                int(data["time_offset_ns"]) if "time_offset_ns" in data else None
            ),
            enabled=bool(data.get("enabled", True)),
        )

    @classmethod
    def from_waymo(
        cls,
        camera_id: str,
        reference_frame: str,
        data: Mapping[str, Any],
        *,
        source_path: Path,
        source_fingerprint: str,
    ) -> CalibrationDraft:
        calibration = CameraCalibration.from_waymo(data)
        intrinsics = CameraIntrinsics.from_camera_calibration(calibration)
        return cls(
            camera_id=camera_id,
            reference_frame=reference_frame,
            base_transform=invert_transform(calibration.t_vehicle_camera),
            base_intrinsics=intrinsics,
            intrinsics=intrinsics,
            source_kind="waymo_embedded",
            source_path=source_path,
            source_fingerprint=source_fingerprint,
        )

    @property
    def effective_transform(self) -> NDArray[np.float64]:
        return self.correction.matrix() @ self.base_transform

    @property
    def is_adjusted(self) -> bool:
        return not self.correction.is_identity or self.intrinsics != self.base_intrinsics

    def with_correction(self, correction: PoseDelta) -> CalibrationDraft:
        return replace(self, correction=correction)

    def with_intrinsics(self, intrinsics: CameraIntrinsics) -> CalibrationDraft:
        return replace(self, intrinsics=intrinsics)

    def reset(self) -> CalibrationDraft:
        return replace(
            self,
            correction=PoseDelta(),
            intrinsics=self.base_intrinsics,
        )

    def baseline_camera_calibration(self) -> CameraCalibration:
        return self._camera_calibration(self.base_transform, self.base_intrinsics)

    def effective_camera_calibration(self) -> CameraCalibration:
        return self._camera_calibration(self.effective_transform, self.intrinsics)

    def _camera_calibration(
        self,
        transform: NDArray[np.float64],
        intrinsics: CameraIntrinsics,
    ) -> CameraCalibration:
        return CameraCalibration.from_generic(
            self.camera_id,
            {
                "intrinsic": intrinsics.matrix(),
                "T_camera_reference": transform.tolist(),
                "image_size": [intrinsics.width, intrinsics.height],
                "distortion_model": intrinsics.distortion_model,
                "distortion_coefficients": list(intrinsics.padded_distortion()),
            },
        )

    def camera_entry(self) -> dict[str, Any]:
        """Return a schema-valid entry retaining baseline and explicit delta."""
        entry: dict[str, Any] = {
            "intrinsic": self.intrinsics.matrix(),
            "T_camera_reference": self.base_transform.tolist(),
            "correction_delta": self.correction.matrix().tolist(),
            "image_size": [self.intrinsics.width, self.intrinsics.height],
            "distortion_model": self.intrinsics.distortion_model,
            "distortion_coefficients": list(self.intrinsics.padded_distortion()),
            "enabled": self.enabled,
        }
        if self.time_offset_ns is not None:
            entry["time_offset_ns"] = self.time_offset_ns
        return entry

    def signature(self) -> tuple[object, ...]:
        return (
            self.correction.x_m,
            self.correction.y_m,
            self.correction.z_m,
            self.correction.roll_deg,
            self.correction.pitch_deg,
            self.correction.yaw_deg,
            self.intrinsics,
        )
