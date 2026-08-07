from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from lidar_label_tool.domain.point_cloud import PointCloudSpec


DataRootKind = Literal["manifest_relative", "absolute_local"]
LidarFormat = Literal["bin", "pcd"]
CameraMode = Literal["display_only", "calibrated"]
SyncMethod = Literal["lidar_only", "exact_stem", "timestamp_nearest"]
MatchStatus = Literal["not_requested", "matched", "unmatched"]


@dataclass(frozen=True, slots=True)
class DataRootV2:
    kind: DataRootKind
    path: str


@dataclass(frozen=True, slots=True)
class CoordinateSystemV2:
    unit: str
    x_axis: str
    y_axis: str
    z_axis: str
    yaw_axis: str
    yaw_unit: str
    yaw_zero: str
    yaw_direction: str
    box_center: str


@dataclass(frozen=True, slots=True)
class TimestampSpecV2:
    path: str
    sample_id_column: str
    value_column: str
    unit: str
    clock_domain: str
    offset_ns: int
    sha256: str
    format: str = "csv"


@dataclass(frozen=True, slots=True)
class LidarSensorV2:
    id: str
    display_name: str
    coordinate_frame: str
    format: LidarFormat
    data_pattern: str
    point_columns: tuple[str, ...]
    point_dtype: str | None
    byte_order: str | None
    timestamp: TimestampSpecV2 | None = None

    @property
    def point_spec(self) -> PointCloudSpec:
        return PointCloudSpec(
            columns=self.point_columns,
            source_frame=self.coordinate_frame,
            dtype=self.point_dtype or "float32",
            byte_order=self.byte_order or "little-endian",
        )


@dataclass(frozen=True, slots=True)
class CameraSensorV2:
    id: str
    display_name: str
    coordinate_frame: str
    image_pattern: str
    timestamp: TimestampSpecV2 | None = None


@dataclass(frozen=True, slots=True)
class FrameIndexGenerationV2:
    method: SyncMethod
    tolerance_ns: int | None = None


@dataclass(frozen=True, slots=True)
class FrameIndexReferenceV2:
    path: str
    sha256: str
    frame_count: int
    generation: FrameIndexGenerationV2
    schema_version: str = "2.0"


@dataclass(frozen=True, slots=True)
class ProfileCameraV2:
    camera_id: str
    mode: CameraMode
    calibration_path: str | None
    calibration_sha256: str | None


@dataclass(frozen=True, slots=True)
class DatasetProfileV2:
    id: str
    display_name: str
    lidar_id: str
    camera: ProfileCameraV2 | None
    frame_index: FrameIndexReferenceV2


@dataclass(frozen=True, slots=True)
class TaxonomyReferenceV2:
    path: str
    sha256: str
    schema_version: str = "2.0"


@dataclass(frozen=True, slots=True)
class DatasetManifestV2:
    dataset_id: str
    display_name: str
    manifest_revision: int
    data_root: DataRootV2
    coordinate_system: CoordinateSystemV2
    lidars: tuple[LidarSensorV2, ...]
    camera: CameraSensorV2 | None
    profiles: tuple[DatasetProfileV2, ...]
    default_profile_id: str
    taxonomy: TaxonomyReferenceV2
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0"
    layout: str = "device_centric_v2"

    def lidar(self, sensor_id: str) -> LidarSensorV2 | None:
        return next((sensor for sensor in self.lidars if sensor.id == sensor_id), None)

    def profile(self, profile_id: str) -> DatasetProfileV2 | None:
        return next((profile for profile in self.profiles if profile.id == profile_id), None)


@dataclass(frozen=True, slots=True)
class FrameLidarSampleV2:
    sensor_id: str
    sample_id: str
    source_sample_id: str
    path: str
    timestamp_ns: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "sample_id": self.sample_id,
            "source_sample_id": self.source_sample_id,
            "path": self.path,
            "timestamp_ns": self.timestamp_ns,
        }


@dataclass(frozen=True, slots=True)
class FrameCameraSampleV2:
    sensor_id: str
    sample_id: str
    source_sample_id: str
    path: str
    timestamp_ns: int | None
    delta_ns: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "sample_id": self.sample_id,
            "source_sample_id": self.source_sample_id,
            "path": self.path,
            "timestamp_ns": self.timestamp_ns,
            "delta_ns": self.delta_ns,
        }


@dataclass(frozen=True, slots=True)
class FrameMatchV2:
    method: SyncMethod
    status: MatchStatus
    tolerance_ns: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "status": self.status,
            "tolerance_ns": self.tolerance_ns,
        }


@dataclass(frozen=True, slots=True)
class FrameIndexRecordV2:
    profile_id: str
    ordinal: int
    frame_id: str
    lidar: FrameLidarSampleV2
    camera: FrameCameraSampleV2 | None
    match: FrameMatchV2
    schema_version: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "ordinal": self.ordinal,
            "frame_id": self.frame_id,
            "lidar": self.lidar.to_dict(),
            "camera": self.camera.to_dict() if self.camera is not None else None,
            "match": self.match.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TaxonomyClassV2:
    id: str
    display_name: str
    color: str
    length: float
    width: float
    height: float
    shortcut: str | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaxonomyV2:
    display_name: str
    classes: tuple[TaxonomyClassV2, ...]
    fallback_class_id: str | None
    source_mappings: Mapping[str, Mapping[str, str]]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0"

    def class_by_id(self, class_id: str) -> TaxonomyClassV2 | None:
        return next((item for item in self.classes if item.id == class_id), None)
