from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from lidar_label_tool.domain.dataset_v2 import (
    DatasetManifestV2,
    DatasetProfileV2,
    FrameIndexRecordV2,
    LidarSensorV2,
)


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def profile_identity_document(
    manifest: DatasetManifestV2,
    profile: DatasetProfileV2,
    lidar: LidarSensorV2,
) -> dict[str, Any]:
    coordinate = manifest.coordinate_system
    return {
        "dataset_id": manifest.dataset_id,
        "profile_id": profile.id,
        "frame_id_policy": "logical_lidar_sample_id",
        "coordinate_system": {
            "unit": coordinate.unit,
            "x_axis": coordinate.x_axis,
            "y_axis": coordinate.y_axis,
            "z_axis": coordinate.z_axis,
            "yaw_axis": coordinate.yaw_axis,
            "yaw_unit": coordinate.yaw_unit,
            "yaw_zero": coordinate.yaw_zero,
            "yaw_direction": coordinate.yaw_direction,
            "box_center": coordinate.box_center,
        },
        "lidar": {
            "id": lidar.id,
            "coordinate_frame": lidar.coordinate_frame,
            "format": lidar.format,
            "point_columns": list(lidar.point_columns),
            "point_dtype": lidar.point_dtype,
            "byte_order": lidar.byte_order,
        },
    }


def profile_identity_sha256(
    manifest: DatasetManifestV2,
    profile: DatasetProfileV2,
    lidar: LidarSensorV2,
) -> str:
    return canonical_json_sha256(profile_identity_document(manifest, profile, lidar))


def lidar_binding_document(record: FrameIndexRecordV2) -> dict[str, Any]:
    return {
        "profile_id": record.profile_id,
        "frame_id": record.frame_id,
        "lidar": {
            "sensor_id": record.lidar.sensor_id,
            "sample_id": record.lidar.sample_id,
            "source_sample_id": record.lidar.source_sample_id,
            "path": record.lidar.path,
        },
    }


def lidar_binding_sha256(record: FrameIndexRecordV2) -> str:
    return canonical_json_sha256(lidar_binding_document(record))


def frame_record_sha256(record: FrameIndexRecordV2) -> str:
    return canonical_json_sha256(record.to_dict())
