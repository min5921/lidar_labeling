from __future__ import annotations

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
