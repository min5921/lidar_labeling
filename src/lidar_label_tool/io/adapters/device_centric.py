from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec
from lidar_label_tool.geometry.transforms import transform_xyz, validate_rigid_transform
from lidar_label_tool.io.dataset import DatasetIndex, SourceFrameData
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader
from lidar_label_tool.io.loaders.pcd_loader import PcdPointCloudLoader


def _json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


class DeviceCentricAdapter:
    """Adapter for manifest-driven sensor/device folders with numbered samples."""

    name = "device_centric"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._loader = BinaryPointCloudLoader()
        self._pcd_loader = PcdPointCloudLoader()
        self._manifest: dict[str, Any] | None = None
        self._index: DatasetIndex | None = None
        self._sensors: dict[str, dict[str, Any]] = {}
        self._frames: dict[str, dict[str, Any]] = {}
        self._point_specs: dict[str, PointCloudSpec] = {}
        self._calibration: dict[str, Any] = {}

    @classmethod
    def can_open(cls, root: Path) -> bool:
        path = Path(root) / "dataset.json"
        if not path.is_file():
            return False
        try:
            data = _json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return data.get("layout") == "device_centric"

    @property
    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            self.scan()
        assert self._manifest is not None
        return self._manifest

    @property
    def camera_calibrations(self) -> Mapping[str, Any]:
        if self._manifest is None:
            self.scan()
        cameras = self._calibration.get("cameras", {})
        return cameras if isinstance(cameras, Mapping) else {}

    @property
    def camera_calibration_count(self) -> int:
        return len(self.camera_calibrations)

    def scan(self) -> DatasetIndex:
        if not self.can_open(self.root):
            raise ValueError(f"not a device-centric dataset: {self.root}")
        manifest = _json(self.root / "dataset.json")
        if str(manifest.get("schema_version")) != "1.0":
            raise ValueError("device-centric dataset schema_version must be '1.0'")
        reference_frame = str(manifest["reference_frame"])
        sensors = manifest.get("sensors")
        if not isinstance(sensors, list) or not sensors:
            raise ValueError("dataset sensors must be a non-empty list")
        self._manifest = manifest
        self._sensors = {}
        self._point_specs = {}
        for sensor in sensors:
            sensor_id = str(sensor["id"])
            if sensor_id in self._sensors:
                raise ValueError(f"duplicate sensor id: {sensor_id}")
            self._sensors[sensor_id] = dict(sensor)
            if sensor["type"] == "lidar":
                self._point_specs[sensor_id] = PointCloudSpec(
                    columns=tuple(str(value) for value in sensor["point_columns"]),
                    dtype=str(sensor.get("point_dtype", "float32")),
                    byte_order=str(sensor.get("byte_order", "little-endian")),
                    source_frame=str(sensor["coordinate_frame"]),
                )
        primary = str(manifest["primary_lidar"])
        if primary not in self._point_specs:
            raise ValueError(f"primary_lidar is not a declared LiDAR: {primary}")
        calibration_path = manifest.get("calibration_path")
        self._calibration = {}
        if calibration_path:
            path = self.root / str(calibration_path)
            if not path.is_file():
                raise ValueError(f"calibration file not found: {path}")
            loaded = _json(path)
            if not isinstance(loaded, dict):
                raise ValueError("calibration root must be an object")
            self._calibration = loaded
        self._validate_lidar_frames(reference_frame)
        self._frames = self._build_frames(manifest, primary)
        if not self._frames:
            raise ValueError("no synchronized frames found")
        lidar_ids = tuple(
            sensor_id
            for sensor_id, sensor in self._sensors.items()
            if sensor["type"] == "lidar"
        )
        camera_ids = tuple(
            sensor_id
            for sensor_id, sensor in self._sensors.items()
            if sensor["type"] == "camera"
        )
        self._index = DatasetIndex(
            root=self.root,
            dataset_id=str(manifest["dataset_id"]),
            adapter_name=self.name,
            frame_ids=tuple(self._frames),
            lidar_ids=lidar_ids,
            camera_ids=camera_ids,
            reference_frame=reference_frame,
            point_spec=self._point_specs[primary],
        )
        return self._index

    def _validate_lidar_frames(self, reference_frame: str) -> None:
        calibrations = self._calibration.get("lidars", {})
        for sensor_id, spec in self._point_specs.items():
            if spec.source_frame == reference_frame:
                continue
            entry = calibrations.get(sensor_id) if isinstance(calibrations, Mapping) else None
            if not isinstance(entry, Mapping) or "T_reference_sensor" not in entry:
                raise ValueError(
                    f"LiDAR {sensor_id} is in {spec.source_frame!r}, but "
                    "T_reference_sensor calibration is missing"
                )
            if entry.get("enabled") is False:
                raise ValueError(
                    f"LiDAR {sensor_id} calibration is disabled; "
                    "sensor-local clouds cannot be merged"
                )
            transform = np.asarray(entry["T_reference_sensor"], dtype=np.float64)
            validate_rigid_transform(transform)

    def _build_frames(self, manifest: Mapping[str, Any], primary: str) -> dict[str, dict[str, Any]]:
        synchronization = manifest["synchronization"]
        mode = str(synchronization["mode"])
        if mode == "index":
            index_path = self.root / str(synchronization["index_path"])
            frames: dict[str, dict[str, Any]] = {}
            with index_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    frame_id = str(item["frame_id"])
                    if frame_id in frames:
                        raise ValueError(f"duplicate frame_id at line {line_number}: {frame_id}")
                    frames[frame_id] = dict(item)
            return frames
        if mode == "exact_stem":
            primary_sensor = self._sensors[primary]
            patterns = primary_sensor["data_patterns"]
            first_pattern = str(patterns[sorted(patterns)[0]])
            sample_ids = self._sample_ids(first_pattern)
            return {
                sample_id: {
                    "frame_id": sample_id,
                    "samples": {
                        f"{sensor['type']}:{sensor_id}": sample_id
                        for sensor_id, sensor in self._sensors.items()
                    },
                }
                for sample_id in sample_ids
            }
        raise ValueError(f"unsupported synchronization mode: {mode}")

    def _sample_ids(self, pattern: str) -> tuple[str, ...]:
        if pattern.count("{sample_id}") != 1:
            raise ValueError(f"data pattern must contain one {{sample_id}}: {pattern}")
        prefix, suffix = pattern.split("{sample_id}")
        matches = []
        for path in self.root.glob(prefix + "*" + suffix):
            relative = path.relative_to(self.root).as_posix()
            if relative.startswith(prefix) and relative.endswith(suffix):
                end = len(relative) - len(suffix) if suffix else len(relative)
                matches.append(relative[len(prefix):end])
        return tuple(sorted(matches))

    @property
    def index(self) -> DatasetIndex:
        return self._index or self.scan()

    def load_source_frame(self, frame_id: str) -> SourceFrameData:
        if frame_id not in self._frames:
            self.scan()
        item = self._frames.get(frame_id)
        if item is None:
            raise KeyError(f"unknown frame: {frame_id}")
        samples = item.get("samples", {})
        point_paths: dict[str, tuple[Path, ...]] = {}
        image_paths: dict[str, Path] = {}
        for sensor_id, sensor in self._sensors.items():
            sample_id = samples.get(f"{sensor['type']}:{sensor_id}", samples.get(sensor_id))
            if sample_id is None:
                continue
            patterns = sensor["data_patterns"]
            if sensor["type"] == "lidar":
                paths = tuple(
                    self.root / str(patterns[key]).format(sample_id=sample_id)
                    for key in sorted(patterns)
                    if key.startswith("return")
                )
                existing = tuple(path for path in paths if path.is_file())
                if existing:
                    point_paths[sensor_id] = existing
            else:
                image_pattern = patterns.get("image")
                if image_pattern:
                    path = self.root / str(image_pattern).format(sample_id=sample_id)
                    if path.is_file():
                        image_paths[sensor_id] = path
        source_labels: dict[str, Path] = {}
        candidates = {
            "laser": (
                self.root / "source_labels" / "laser" / f"{frame_id}.json",
                self.root / "source_labels" / f"{frame_id}.json",
            ),
            "camera": (self.root / "source_labels" / "camera" / f"{frame_id}.json",),
            "projected_lidar": (
                self.root / "source_labels" / "projected_lidar" / f"{frame_id}.json",
            ),
        }
        for layer, paths in candidates.items():
            path = next((candidate for candidate in paths if candidate.is_file()), None)
            if path is not None:
                source_labels[layer] = path
        metadata = {
            "timestamp_us": item.get("timestamp_us"),
            "calibration_path": self.manifest.get("calibration_path"),
            "reference_frame": self.index.reference_frame,
            "sensor_status": {
                sensor_id: (
                    "not_required"
                    if self._point_specs[sensor_id].source_frame == self.index.reference_frame
                    else "applied"
                )
                for sensor_id in point_paths
            },
        }
        return SourceFrameData(
            dataset_root=self.root,
            dataset_id=self.index.dataset_id,
            frame_id=frame_id,
            point_cloud_paths=point_paths,
            image_paths=image_paths,
            source_label_paths=source_labels,
            point_spec=self.index.point_spec,
            timestamp_micros=str(item["timestamp_us"]) if item.get("timestamp_us") else None,
            metadata=metadata,
        )

    def load_cloud_from_source(
        self, frame: SourceFrameData, sensor_id: str, return_id: str = "1"
    ) -> PointCloudData:
        paths = frame.point_cloud_paths.get(sensor_id)
        if not paths:
            raise KeyError(f"sensor {sensor_id!r} not found in {frame.frame_id}")
        index = int(return_id) - 1
        if index < 0 or index >= len(paths):
            raise KeyError(f"return {return_id!r} not found for {sensor_id!r}")
        spec = self._point_specs[sensor_id]
        loader = self._pcd_loader if paths[index].suffix.lower() == ".pcd" else self._loader
        if not loader.can_load(paths[index], spec):
            raise ValueError(f"unsupported point cloud file: {paths[index]}")
        cloud = loader.load(
            paths[index], spec, sensor_id=sensor_id, return_id=return_id
        )
        if spec.source_frame == self.index.reference_frame:
            return cloud
        entry = self._calibration["lidars"][sensor_id]
        transform = np.asarray(entry["T_reference_sensor"], dtype=np.float64)
        correction = entry.get("correction_delta")
        if correction is not None:
            transform = np.asarray(correction, dtype=np.float64) @ transform
        xyz = transform_xyz(cloud.xyz, transform)
        metadata = dict(cloud.metadata)
        metadata["calibration_status"] = "applied"
        return replace(
            cloud,
            xyz=np.ascontiguousarray(xyz),
            source_frame=self.index.reference_frame,
            metadata=metadata,
        )
