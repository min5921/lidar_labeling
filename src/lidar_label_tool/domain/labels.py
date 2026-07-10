from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import math
from typing import Any, Mapping


FRAME_STATUSES = {"unvisited", "in_progress", "reviewed", "skipped"}
CALIBRATION_MODES = {"auto", "on", "off"}
_OBJECT_KNOWN_FIELDS = {"id", "class_name", "box3d", "attributes", "source"}
_FRAME_KNOWN_FIELDS = {
    "schema_version",
    "dataset_id",
    "frame_id",
    "revision",
    "frame_status",
    "saved_at_utc",
    "point_cloud_paths",
    "point_cloud_path",
    "image_paths",
    "image_path",
    "calib_path",
    "calibration_path",
    "reference_frame",
    "coordinate_system",
    "provenance",
    "calibration_state",
    "objects",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_yaw(yaw: float) -> float:
    """Normalize radians to [-pi, pi)."""
    if not math.isfinite(yaw):
        raise ValueError("yaw must be finite")
    return (yaw + math.pi) % (2.0 * math.pi) - math.pi


@dataclass(frozen=True, slots=True)
class Box3D:
    """A box in reference coordinates, centered at x/y/z."""

    x: float
    y: float
    z: float
    length: float
    width: float
    height: float
    yaw: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.z, self.length, self.width, self.height, self.yaw)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Box3D values must be finite")
        if self.length <= 0 or self.width <= 0 or self.height <= 0:
            raise ValueError("Box3D dimensions must be positive")
        object.__setattr__(self, "yaw", normalize_yaw(self.yaw))

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "yaw": self.yaw,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Box3D:
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            z=float(data["z"]),
            length=float(data["length"]),
            width=float(data["width"]),
            height=float(data["height"]),
            yaw=float(data["yaw"]),
        )


@dataclass(frozen=True, slots=True)
class LabeledObject:
    id: str
    class_name: str
    box3d: Box3D
    attributes: Mapping[str, Any] = field(default_factory=dict)
    source: Mapping[str, Any] = field(default_factory=dict)
    extra_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("object id must not be empty")
        if not self.class_name:
            raise ValueError("class_name must not be empty")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = dict(self.extra_fields)
        result.update(
            {
                "id": self.id,
                "class_name": self.class_name,
                "box3d": self.box3d.to_dict(),
                "attributes": dict(self.attributes),
            }
        )
        if self.source:
            result["source"] = dict(self.source)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LabeledObject:
        return cls(
            id=str(data["id"]),
            class_name=str(data["class_name"]),
            box3d=Box3D.from_dict(data["box3d"]),
            attributes=dict(data.get("attributes", {})),
            source=dict(data.get("source", {})),
            extra_fields={
                str(key): value
                for key, value in data.items()
                if key not in _OBJECT_KNOWN_FIELDS
            },
        )


@dataclass(frozen=True, slots=True)
class FrameLabel:
    dataset_id: str
    frame_id: str
    point_cloud_paths: Mapping[str, tuple[str, ...]]
    image_paths: Mapping[str, str]
    reference_frame: str
    objects: tuple[LabeledObject, ...] = ()
    revision: int = 0
    frame_status: str = "unvisited"
    saved_at_utc: str = field(default_factory=utc_now_iso)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    calibration_state: Mapping[str, Any] = field(default_factory=dict)
    coordinate_system: Mapping[str, str] = field(
        default_factory=lambda: {"x": "forward", "y": "left", "z": "up"}
    )
    extra_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.frame_id or not self.reference_frame:
            raise ValueError("dataset_id, frame_id and reference_frame are required")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        if self.frame_status not in FRAME_STATUSES:
            raise ValueError(f"unsupported frame status: {self.frame_status}")
        object_ids = [obj.id for obj in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("object ids must be unique within a frame")

    def with_saved_revision(self, revision: int) -> FrameLabel:
        return replace(self, revision=revision, saved_at_utc=utc_now_iso())

    def to_dict(self) -> dict[str, Any]:
        calibration_state = dict(self.calibration_state) or {
            "mode": "auto",
            "fingerprint": None,
            "sensor_status": {},
        }
        provenance = dict(self.provenance) or {
            "source_format": "none",
            "source_paths": [],
            "source_fingerprints": {},
        }
        result: dict[str, Any] = dict(self.extra_fields)
        result.update(
            {
                "schema_version": "1.0",
                "dataset_id": self.dataset_id,
                "frame_id": self.frame_id,
                "revision": self.revision,
                "frame_status": self.frame_status,
                "saved_at_utc": self.saved_at_utc,
                "point_cloud_paths": {
                    sensor: list(paths) for sensor, paths in self.point_cloud_paths.items()
                },
                "image_paths": dict(self.image_paths),
                "reference_frame": self.reference_frame,
                "coordinate_system": dict(self.coordinate_system),
                "provenance": provenance,
                "calibration_state": calibration_state,
                "objects": [obj.to_dict() for obj in self.objects],
            }
        )
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FrameLabel:
        raw_paths = data.get("point_cloud_paths", {})
        if not raw_paths and data.get("point_cloud_path"):
            raw_paths = {"PRIMARY": data["point_cloud_path"]}
        point_cloud_paths: dict[str, tuple[str, ...]] = {}
        for sensor, paths in raw_paths.items():
            if isinstance(paths, str):
                point_cloud_paths[str(sensor)] = (paths,)
            else:
                point_cloud_paths[str(sensor)] = tuple(str(path) for path in paths)
        return cls(
            dataset_id=str(data["dataset_id"]),
            frame_id=str(data["frame_id"]),
            point_cloud_paths=point_cloud_paths,
            image_paths={
                str(k): str(v)
                for k, v in (
                    data.get("image_paths")
                    or ({"PRIMARY": data["image_path"]} if data.get("image_path") else {})
                ).items()
            },
            reference_frame=str(data["reference_frame"]),
            objects=tuple(LabeledObject.from_dict(obj) for obj in data.get("objects", [])),
            revision=int(data.get("revision", 0)),
            frame_status=str(data.get("frame_status", "unvisited")),
            saved_at_utc=str(data.get("saved_at_utc", utc_now_iso())),
            provenance=dict(data.get("provenance", {})),
            calibration_state=dict(data.get("calibration_state", {})),
            coordinate_system=dict(
                data.get("coordinate_system", {"x": "forward", "y": "left", "z": "up"})
            ),
            extra_fields={
                str(key): value
                for key, value in data.items()
                if key not in _FRAME_KNOWN_FIELDS
            },
        )
