from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

import numpy as np

from lidar_label_tool.geometry.transforms import invert_transform
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter


_FRAME_NUMBER = re.compile(r"^frame_(\d+)$")


def _sample_id(frame_id: str) -> str:
    match = _FRAME_NUMBER.fullmatch(frame_id)
    if match is None:
        return frame_id
    return f"{int(match.group(1)):06d}"


def _link_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _merge_bins(
    paths: list[Path], target: Path, stride_bytes: int, output_format: str
) -> int:
    sizes = [path.stat().st_size for path in paths]
    if any(size % stride_bytes for size in sizes):
        raise ValueError(f"source BIN stride mismatch while merging {target.name}")
    point_count = sum(size // stride_bytes for size in sizes)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        if output_format == "pcd":
            output.write(
                (
                    "# .PCD v0.7\n"
                    "VERSION 0.7\n"
                    "FIELDS x y z intensity elongation nlz_flag\n"
                    "SIZE 4 4 4 4 4 4\n"
                    "TYPE F F F F F F\n"
                    "COUNT 1 1 1 1 1 1\n"
                    f"WIDTH {point_count}\n"
                    "HEIGHT 1\n"
                    f"POINTS {point_count}\n"
                    "DATA binary\n"
                ).encode("ascii")
            )
        for path in paths:
            with path.open("rb") as source:
                shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
    return point_count


def _generic_calibration(adapter: WaymoFrameCentricAdapter) -> dict[str, object]:
    identity = np.eye(4, dtype=np.float64).tolist()
    cameras: dict[str, object] = {}
    for raw in adapter.segment.get("camera_calibrations", []):
        fu, fv, cu, cv, k1, k2, p1, p2, k3 = (
            float(value) for value in raw["intrinsic"]
        )
        t_reference_camera = np.asarray(
            raw["extrinsic"]["transform"], dtype=np.float64
        ).reshape(4, 4)
        cameras[str(raw["name"])] = {
            "intrinsic": [[fu, 0.0, cu], [0.0, fv, cv], [0.0, 0.0, 1.0]],
            "T_camera_reference": invert_transform(t_reference_camera).tolist(),
            "image_size": [int(raw["width"]), int(raw["height"])],
            "distortion_model": "brown_conrady",
            "distortion_coefficients": [k1, k2, p1, p2, k3],
            "enabled": True,
        }
    return {
        "schema_version": "1.0",
        "reference_frame": "vehicle",
        "lidars": {
            "MERGED": {
                "T_reference_sensor": identity,
                "enabled": True,
            }
        },
        "cameras": cameras,
        "metadata": {
            "source_format": "waymo_frame_centric",
            "note": "LiDAR files were already in vehicle frame before concatenation.",
        },
    }


def convert(
    source_root: Path,
    output_root: Path,
    *,
    output_format: str = "bin",
    limit: int | None = None,
) -> None:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"output already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.with_name(f".{output_root.name}.building-{uuid4().hex}")
    staging.mkdir()

    adapter = WaymoFrameCentricAdapter(source_root)
    index = adapter.scan()
    if index.point_spec.source_frame != "vehicle":
        raise ValueError(
            "source LiDAR is not declared in vehicle frame; apply calibration before merging"
        )
    expected_columns = ("x", "y", "z", "intensity", "elongation", "nlz_flag")
    if index.point_spec.columns != expected_columns:
        raise ValueError(
            f"converter expects columns {expected_columns}, found {index.point_spec.columns}"
        )
    frame_ids = index.frame_ids[:limit] if limit is not None else index.frame_ids
    extension = ".pcd" if output_format == "pcd" else ".bin"
    lidar_pattern = f"sensors/lidar/MERGED/frames/{{sample_id}}{extension}"
    camera_patterns = {
        camera: f"sensors/camera/{camera}/images/{{sample_id}}.jpg"
        for camera in index.camera_ids
    }
    sensors: list[dict[str, object]] = [
        {
            "id": "MERGED",
            "type": "lidar",
            "coordinate_frame": "vehicle",
            "data_patterns": {"return1": lidar_pattern},
            "point_columns": list(index.point_spec.columns),
            "point_dtype": "float32",
            "byte_order": "little-endian",
        }
    ]
    sensors.extend(
        {
            "id": camera,
            "type": "camera",
            "coordinate_frame": f"camera:{camera}",
            "data_patterns": {"image": pattern},
        }
        for camera, pattern in camera_patterns.items()
    )
    manifest = {
        "schema_version": "1.0",
        "dataset_id": f"{index.dataset_id}_merged",
        "layout": "device_centric",
        "reference_frame": "vehicle",
        "primary_lidar": "MERGED",
        "sensors": sensors,
        "synchronization": {"mode": "index", "index_path": "sync/frames.jsonl"},
        "calibration_path": "calibration/calibration.json",
    }
    (staging / "dataset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    calibration_path = staging / "calibration" / "calibration.json"
    calibration_path.parent.mkdir(parents=True)
    calibration_path.write_text(
        json.dumps(_generic_calibration(adapter), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sync_path = staging / "sync" / "frames.jsonl"
    sync_path.parent.mkdir(parents=True)
    total_points = 0
    with sync_path.open("x", encoding="utf-8", newline="\n") as sync_stream:
        for position, frame_id in enumerate(frame_ids, start=1):
            source = adapter.load_source_frame(frame_id)
            sample_id = _sample_id(frame_id)
            input_bins = [
                path
                for sensor in sorted(source.point_cloud_paths)
                for path in source.point_cloud_paths[sensor]
            ]
            lidar_target = staging / lidar_pattern.format(sample_id=sample_id)
            total_points += _merge_bins(
                input_bins,
                lidar_target,
                index.point_spec.point_stride_bytes,
                output_format,
            )
            samples: dict[str, str] = {"lidar:MERGED": sample_id}
            for camera, source_image in source.image_paths.items():
                suffix = source_image.suffix.lower()
                target_pattern = camera_patterns[camera]
                if suffix not in {".jpg", ".jpeg"}:
                    target_pattern = target_pattern.rsplit(".", 1)[0] + suffix
                    manifest_camera = next(
                        item for item in sensors if item["id"] == camera
                    )
                    manifest_camera["data_patterns"]["image"] = target_pattern
                _link_or_copy(
                    source_image, staging / target_pattern.format(sample_id=sample_id)
                )
                samples[f"camera:{camera}"] = sample_id
            for layer, source_label in source.source_label_paths.items():
                _copy_file(
                    source_label,
                    staging / "source_labels" / layer / f"{sample_id}.json",
                )
            sync_stream.write(
                json.dumps(
                    {
                        "frame_id": sample_id,
                        "timestamp_us": source.timestamp_micros,
                        "samples": samples,
                        "source_frame_id": frame_id,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            if position % 10 == 0 or position == len(frame_ids):
                print(
                    f"converted {position}/{len(frame_ids)} frames · "
                    f"{total_points:,} points",
                    flush=True,
                )
    (staging / "dataset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    staging.replace(output_root)
    print(f"created: {output_root}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--format", choices=("bin", "pcd"), default="bin")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    convert(args.source, args.output, output_format=args.format, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
