from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.dataset import SourceFrameData


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class WaymoLabelImporter:
    def __init__(
        self,
        class_mapping: Mapping[str, str],
        source_format: str = "waymo_frame_json",
    ) -> None:
        self.class_mapping = dict(class_mapping)
        self.source_format = source_format

    def import_laser_labels(self, frame: SourceFrameData) -> FrameLabel:
        label_path = frame.source_label_paths.get("laser")
        raw_objects: list[dict[str, Any]] = []
        if label_path is not None:
            with label_path.open("r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            if not isinstance(loaded, list):
                raise ValueError(f"Waymo laser label root must be a list: {label_path}")
            raw_objects = loaded

        objects = tuple(self._import_object(item) for item in raw_objects)
        source_paths = [
            path.relative_to(frame.dataset_root).as_posix()
            for path in frame.source_label_paths.values()
        ]
        source_fingerprints = {
            path.relative_to(frame.dataset_root).as_posix(): sha256_file(path)
            for path in frame.source_label_paths.values()
        }
        point_paths = {
            sensor: tuple(path.relative_to(frame.dataset_root).as_posix() for path in paths)
            for sensor, paths in frame.point_cloud_paths.items()
        }
        image_paths = {
            sensor: path.relative_to(frame.dataset_root).as_posix()
            for sensor, path in frame.image_paths.items()
        }
        reference_frame = str(frame.metadata.get("reference_frame", "vehicle"))
        metadata_status = frame.metadata.get("sensor_status")
        sensor_status = (
            dict(metadata_status)
            if isinstance(metadata_status, Mapping)
            else {
                sensor: "not_required"
                for sensor in frame.point_cloud_paths
                if frame.point_spec.source_frame == reference_frame
            }
        )
        calibration_relative = frame.metadata.get("calibration_path")
        calibration_path = (
            frame.dataset_root / str(calibration_relative)
            if calibration_relative
            else frame.dataset_root / "segment.json"
        )
        calibration_fingerprint = (
            sha256_file(calibration_path) if calibration_path.is_file() else None
        )
        return FrameLabel(
            dataset_id=frame.dataset_id,
            frame_id=frame.frame_id,
            point_cloud_paths=point_paths,
            image_paths=image_paths,
            reference_frame=reference_frame,
            objects=objects,
            revision=0,
            frame_status="unvisited",
            provenance={
                "source_format": self.source_format,
                "source_paths": source_paths,
                "source_fingerprints": source_fingerprints,
            },
            calibration_state={
                "mode": "auto",
                "fingerprint": calibration_fingerprint,
                "sensor_status": sensor_status,
            },
        )

    def load_reference_layers(self, frame: SourceFrameData) -> dict[str, Any]:
        layers: dict[str, Any] = {}
        for name in ("camera", "projected_lidar"):
            if name in frame.source_label_paths:
                layers[name] = self.load_reference_layer(frame, name)
        return layers

    @staticmethod
    def load_reference_layer(frame: SourceFrameData, name: str) -> Any:
        path = frame.source_label_paths.get(name)
        if path is None:
            raise KeyError(f"reference layer {name!r} is not available")
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def class_counts(self, label: FrameLabel) -> Counter[str]:
        return Counter(obj.class_name for obj in label.objects)

    def _import_object(self, item: Mapping[str, Any]) -> LabeledObject:
        raw_box = item.get("box")
        if not isinstance(raw_box, Mapping):
            raise ValueError(f"Waymo object is missing box: {item.get('id', '<unknown>')}")
        source_type = str(item.get("type", "TYPE_UNKNOWN"))
        class_name = self.class_mapping.get(source_type, "Unknown")
        attributes = dict(item.get("metadata", {}))
        for key in (
            "num_lidar_points_in_box",
            "num_top_lidar_points_in_box",
            "detection_difficulty_level",
            "tracking_difficulty_level",
            "most_visible_camera_name",
        ):
            if key in item:
                attributes[key] = item[key]
        return LabeledObject(
            id=str(item["id"]),
            class_name=class_name,
            box3d=Box3D(
                x=float(raw_box["center_x"]),
                y=float(raw_box["center_y"]),
                z=float(raw_box["center_z"]),
                length=float(raw_box["length"]),
                width=float(raw_box["width"]),
                height=float(raw_box["height"]),
                yaw=float(raw_box.get("heading", 0.0)),
            ),
            attributes=attributes,
            source={"format": "waymo_json", "type": source_type, "raw": dict(item)},
        )
