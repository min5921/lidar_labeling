from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


CLASS_MAPPING = {
    "TYPE_VEHICLE": "Car",
    "TYPE_PEDESTRIAN": "Pedestrian",
    "TYPE_CYCLIST": "Cyclist",
    "TYPE_SIGN": "Sign",
    "TYPE_UNKNOWN": "Unknown",
}


def create_device_dataset(root: Path, *, frame_count: int = 1) -> None:
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "preflight_fixture",
        "layout": "device_centric",
        "reference_frame": "vehicle",
        "primary_lidar": "MERGED",
        "sensors": [
            {
                "id": "MERGED",
                "type": "lidar",
                "coordinate_frame": "vehicle",
                "data_patterns": {"return1": "sensors/lidar/MERGED/{sample_id}.bin"},
                "point_columns": ["x", "y", "z", "intensity"],
                "point_dtype": "float32",
            }
        ],
        "synchronization": {"mode": "index", "index_path": "sync/frames.jsonl"},
    }
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    sync = root / "sync" / "frames.jsonl"
    sync.parent.mkdir(parents=True)
    frames = [
        {
            "frame_id": f"{number:06d}",
            "samples": {"lidar:MERGED": f"{number:06d}"},
        }
        for number in range(frame_count)
    ]
    sync.write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames), encoding="utf-8"
    )
    lidar = root / "sensors" / "lidar" / "MERGED"
    lidar.mkdir(parents=True)
    for number in range(frame_count):
        np.array([[1, 2, 3, 0.5]], dtype="<f4").tofile(lidar / f"{number:06d}.bin")


def create_v2_dataset(
    root: Path,
    *,
    frame_count: int = 2,
    with_camera: bool = False,
    camera_clock_domain: str = "bag",
) -> dict[str, object]:
    generation = root / "generations" / "generation-000001"
    sync = generation / "sync"
    lidar = root / "sensors" / "lidar" / "AEVA" / "frames"
    sync.mkdir(parents=True)
    lidar.mkdir(parents=True)
    camera_root = root / "sensors" / "camera" / "HEAD_CAMERA" / "images"
    if with_camera:
        camera_root.mkdir(parents=True)

    taxonomy = {
        "schema_version": "2.0",
        "display_name": "기본 클래스",
        "classes": [
            {
                "id": "car",
                "display_name": "자동차",
                "color": "#00D084",
                "default_size_m": {
                    "length": 4.2,
                    "width": 1.8,
                    "height": 1.6,
                },
            }
        ],
        "fallback_class_id": "car",
    }
    taxonomy_path = generation / "taxonomy.json"
    taxonomy_path.write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    records = []
    lidar_timestamp_rows = ["sample_id,bag_time_ns"]
    camera_timestamp_rows = ["sample_id,bag_time_ns"]
    for number in range(frame_count):
        sample_id = f"{number:06d}"
        relative_path = f"sensors/lidar/AEVA/frames/{sample_id}.bin"
        np.array([[1, 2, 3, 0.5]], dtype="<f4").tofile(root / relative_path)
        lidar_timestamp = 1_000_000 + number * 100
        camera_timestamp = lidar_timestamp + 10
        camera_record = None
        match: dict[str, object] = {
            "method": "lidar_only",
            "status": "not_requested",
            "tolerance_ns": None,
        }
        if with_camera:
            image_path = f"sensors/camera/HEAD_CAMERA/images/{sample_id}.jpg"
            (root / image_path).write_bytes(b"image")
            camera_record = {
                "sensor_id": "head_camera",
                "sample_id": sample_id,
                "source_sample_id": sample_id,
                "path": image_path,
                "timestamp_ns": camera_timestamp,
                "delta_ns": camera_timestamp - lidar_timestamp,
            }
            match = {
                "method": "timestamp_nearest",
                "status": "matched",
                "tolerance_ns": 50,
            }
            lidar_timestamp_rows.append(f"{sample_id},{lidar_timestamp}")
            camera_timestamp_rows.append(f"{sample_id},{camera_timestamp}")
        records.append(
            {
                "schema_version": "2.0",
                "profile_id": "aeva_profile",
                "ordinal": number,
                "frame_id": sample_id,
                "lidar": {
                    "sensor_id": "aeva",
                    "sample_id": sample_id,
                    "source_sample_id": sample_id,
                    "path": relative_path,
                    "timestamp_ns": lidar_timestamp if with_camera else None,
                },
                "camera": camera_record,
                "match": match,
            }
        )
    index_bytes = "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    ).encode("utf-8")
    index_path = sync / "aeva_profile.frames.jsonl"
    index_path.write_bytes(index_bytes)

    lidar_entry: dict[str, object] = {
        "id": "aeva",
        "display_name": "AEVA",
        "coordinate_frame": "lidar:AEVA",
        "format": "bin",
        "data_pattern": "sensors/lidar/AEVA/frames/{sample_id}.bin",
        "point_columns": ["x", "y", "z", "intensity"],
        "point_dtype": "float32",
        "byte_order": "little-endian",
    }
    camera_entry: dict[str, object] | None = None
    profile_camera: dict[str, object] | None = None
    generation_method = "lidar_only"
    generation_tolerance: int | None = None
    if with_camera:
        timestamps = root / "timestamps"
        timestamps.mkdir()
        lidar_timestamp_path = timestamps / "AEVA.csv"
        camera_timestamp_path = timestamps / "HEAD_CAMERA.csv"
        lidar_timestamp_path.write_text(
            "\n".join(lidar_timestamp_rows) + "\n",
            encoding="utf-8",
        )
        camera_timestamp_path.write_text(
            "\n".join(camera_timestamp_rows) + "\n",
            encoding="utf-8",
        )
        lidar_entry["timestamp"] = {
            "format": "csv",
            "path": "timestamps/AEVA.csv",
            "sample_id_column": "sample_id",
            "value_column": "bag_time_ns",
            "unit": "ns",
            "clock_domain": "bag",
            "offset_ns": 0,
            "sha256": _file_sha256(lidar_timestamp_path),
        }
        camera_entry = {
            "id": "head_camera",
            "display_name": "Head camera",
            "coordinate_frame": "camera:HEAD_CAMERA",
            "image_pattern": "sensors/camera/HEAD_CAMERA/images/{sample_id}.jpg",
            "timestamp": {
                "format": "csv",
                "path": "timestamps/HEAD_CAMERA.csv",
                "sample_id_column": "sample_id",
                "value_column": "bag_time_ns",
                "unit": "ns",
                "clock_domain": camera_clock_domain,
                "offset_ns": 0,
                "sha256": _file_sha256(camera_timestamp_path),
            },
        }
        profile_camera = {
            "camera_id": "head_camera",
            "mode": "display_only",
            "calibration_path": None,
            "calibration_sha256": None,
        }
        generation_method = "timestamp_nearest"
        generation_tolerance = 50

    manifest: dict[str, object] = {
        "schema_version": "2.0",
        "dataset_id": "ds_fixture_v2",
        "display_name": "한글 데이터 세트 01",
        "manifest_revision": 1,
        "layout": "device_centric_v2",
        "data_root": {"kind": "manifest_relative", "path": "."},
        "coordinate_system": {
            "unit": "meter",
            "x_axis": "forward",
            "y_axis": "left",
            "z_axis": "up",
            "yaw_axis": "+z",
            "yaw_unit": "radian",
            "yaw_zero": "+x",
            "yaw_direction": "counterclockwise",
            "box_center": "geometric_center",
        },
        "labeling_policy": {
            "active_lidar": "one_per_profile",
            "merge_lidars": False,
            "label_namespace": "profile_lidar",
            "frame_id_policy": "logical_lidar_sample_id",
        },
        "lidars": [lidar_entry],
        "camera": camera_entry,
        "profiles": [
            {
                "id": "aeva_profile",
                "display_name": "AEVA 라벨링",
                "lidar_id": "aeva",
                "camera": profile_camera,
                "frame_index": {
                    "schema_version": "2.0",
                    "path": (
                        "generations/generation-000001/sync/"
                        "aeva_profile.frames.jsonl"
                    ),
                    "sha256": hashlib.sha256(index_bytes).hexdigest(),
                    "frame_count": frame_count,
                    "generation": {
                        "method": generation_method,
                        "tolerance_ns": generation_tolerance,
                    },
                },
            }
        ],
        "default_profile_id": "aeva_profile",
        "taxonomy": {
            "schema_version": "2.0",
            "path": "generations/generation-000001/taxonomy.json",
            "sha256": _file_sha256(taxonomy_path),
        },
    }
    (root / "dataset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_source_labels(root: Path, frame_id: str, objects: list[dict[str, object]]) -> Path:
    path = root / "source_labels" / "laser" / f"{frame_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def source_object(
    object_id: str,
    source_type: str = "TYPE_VEHICLE",
) -> dict[str, object]:
    return {
        "id": object_id,
        "type": source_type,
        "box": {
            "center_x": 1.0,
            "center_y": 2.0,
            "center_z": 0.5,
            "length": 4.0,
            "width": 2.0,
            "height": 1.5,
            "heading": 0.25,
        },
    }
