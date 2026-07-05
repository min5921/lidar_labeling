from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec
from lidar_label_tool.io.dataset import DatasetIndex, SourceFrameData
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader


_LIDAR_FILE = re.compile(r"^(?P<sensor>.+)_return(?P<return_id>\d+)\.bin$", re.IGNORECASE)
_FRAME_DIR = re.compile(r"^frame_(?P<number>\d+)$")


def _json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _frame_sort_key(path: Path) -> tuple[int, str]:
    match = _FRAME_DIR.match(path.name)
    return (int(match.group("number")) if match else 2**31 - 1, path.name)


class WaymoFrameCentricAdapter:
    """Adapter for the provided frame_xxx/lidar|camera|labels dataset."""

    name = "frame_centric_waymo"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._loader = BinaryPointCloudLoader()
        self._index: DatasetIndex | None = None
        self._segment: dict[str, Any] | None = None

    @classmethod
    def can_open(cls, root: Path) -> bool:
        root = Path(root)
        return (root / "schema.json").is_file() and (root / "segment.json").is_file()

    def scan(self) -> DatasetIndex:
        if not self.can_open(self.root):
            raise ValueError(f"not a supported Waymo frame-centric dataset: {self.root}")
        schema = _json(self.root / "schema.json")
        segment = _json(self.root / "segment.json")
        self._segment = segment
        lidar_bin = schema["lidar_bin"]
        coordinates = str(schema.get("coordinates", "unknown"))
        source_frame = "vehicle" if "vehicle frame" in coordinates.lower() else coordinates
        point_spec = PointCloudSpec(
            columns=tuple(str(column) for column in lidar_bin["columns"]),
            dtype=str(lidar_bin.get("dtype", "float32")),
            byte_order=str(schema.get("byte_order", "little-endian")),
            source_frame=source_frame,
        )
        frame_dirs = sorted(
            (path for path in self.root.iterdir() if path.is_dir() and _FRAME_DIR.match(path.name)),
            key=_frame_sort_key,
        )
        if not frame_dirs:
            raise ValueError(f"no frame_xxx directories found under {self.root}")
        lidar_ids = tuple(str(item["name"]) for item in segment.get("laser_calibrations", []))
        camera_ids = tuple(str(item["name"]) for item in segment.get("camera_calibrations", []))
        dataset_id = str(segment.get("scene_name") or segment.get("record") or self.root.name)
        self._index = DatasetIndex(
            root=self.root,
            dataset_id=dataset_id,
            adapter_name=self.name,
            frame_ids=tuple(path.name for path in frame_dirs),
            lidar_ids=lidar_ids,
            camera_ids=camera_ids,
            reference_frame="vehicle",
            point_spec=point_spec,
        )
        return self._index

    @property
    def index(self) -> DatasetIndex:
        return self._index or self.scan()

    @property
    def segment(self) -> dict[str, Any]:
        if self._segment is None:
            self.scan()
        assert self._segment is not None
        return self._segment

    @property
    def camera_calibration_count(self) -> int:
        return len(self.segment.get("camera_calibrations", []))

    def load_source_frame(self, frame_id: str) -> SourceFrameData:
        index = self.index
        if frame_id not in index.frame_ids:
            raise KeyError(f"unknown frame: {frame_id}")
        frame_dir = self.root / frame_id
        lidar_dir = frame_dir / "lidar"
        point_paths: dict[str, list[tuple[int, Path]]] = {}
        for path in lidar_dir.glob("*.bin"):
            match = _LIDAR_FILE.match(path.name)
            if not match:
                continue
            sensor = match.group("sensor")
            return_number = int(match.group("return_id"))
            point_paths.setdefault(sensor, []).append((return_number, path))
        ordered_points = {
            sensor: tuple(path for _, path in sorted(items))
            for sensor, items in sorted(point_paths.items())
        }

        camera_dir = frame_dir / "camera"
        image_paths = {
            path.stem: path
            for path in sorted(camera_dir.iterdir())
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        }
        label_dir = frame_dir / "labels"
        source_labels = {
            "laser": label_dir / "laser_labels.json",
            "camera": label_dir / "camera_labels.json",
            "projected_lidar": label_dir / "projected_lidar_labels.json",
        }
        source_labels = {name: path for name, path in source_labels.items() if path.is_file()}
        metadata_path = frame_dir / "metadata.json"
        metadata = _json(metadata_path) if metadata_path.is_file() else {}
        return SourceFrameData(
            dataset_root=self.root,
            dataset_id=index.dataset_id,
            frame_id=frame_id,
            point_cloud_paths=ordered_points,
            image_paths=image_paths,
            source_label_paths=source_labels,
            point_spec=index.point_spec,
            timestamp_micros=str(metadata["timestamp_micros"])
            if "timestamp_micros" in metadata
            else None,
            metadata=metadata,
        )

    def load_point_cloud(self, frame_id: str, sensor_id: str, return_id: str = "1") -> PointCloudData:
        frame = self.load_source_frame(frame_id)
        return self.load_cloud_from_source(frame, sensor_id, return_id)

    def load_cloud_from_source(
        self, frame: SourceFrameData, sensor_id: str, return_id: str = "1"
    ) -> PointCloudData:
        paths = frame.point_cloud_paths.get(sensor_id)
        if not paths:
            raise KeyError(f"sensor {sensor_id!r} not found in {frame.frame_id}")
        return_number = int(return_id)
        if return_number < 1 or return_number > len(paths):
            raise KeyError(
                f"return {return_id!r} not found for {sensor_id!r} in {frame.frame_id}"
            )
        return self._loader.load(
            paths[return_number - 1],
            frame.point_spec,
            sensor_id=sensor_id,
            return_id=str(return_number),
        )
