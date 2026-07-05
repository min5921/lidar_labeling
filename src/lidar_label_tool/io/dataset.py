from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from lidar_label_tool.domain.point_cloud import PointCloudSpec


@dataclass(frozen=True, slots=True)
class SourceFrameData:
    dataset_root: Path
    dataset_id: str
    frame_id: str
    point_cloud_paths: Mapping[str, tuple[Path, ...]]
    image_paths: Mapping[str, Path]
    source_label_paths: Mapping[str, Path]
    point_spec: PointCloudSpec
    timestamp_micros: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DatasetIndex:
    root: Path
    dataset_id: str
    adapter_name: str
    frame_ids: tuple[str, ...]
    lidar_ids: tuple[str, ...]
    camera_ids: tuple[str, ...]
    reference_frame: str
    point_spec: PointCloudSpec

    @property
    def frame_count(self) -> int:
        return len(self.frame_ids)


class DatasetAdapter(Protocol):
    name: str
    root: Path

    def scan(self) -> DatasetIndex: ...

    def load_source_frame(self, frame_id: str) -> SourceFrameData: ...

    def load_cloud_from_source(
        self, frame: SourceFrameData, sensor_id: str, return_id: str = "1"
    ) -> PointCloudData: ...
