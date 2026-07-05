from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.dataset import DatasetAdapter, SourceFrameData
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import FrameSessionService


@dataclass(frozen=True, slots=True)
class FrameLoadPayload:
    source: SourceFrameData
    label: FrameLabel
    label_origin: str
    clouds: Mapping[str, tuple[PointCloudData, ...]]
    reference_layers: Mapping[str, Any]


def load_frame_payload(
    adapter: DatasetAdapter,
    importer: WaymoLabelImporter,
    frame_id: str,
    repository: LabelRepository | None = None,
) -> FrameLoadPayload:
    opened = FrameSessionService(adapter, importer, repository).open_frame(frame_id)
    clouds: dict[str, tuple[PointCloudData, ...]] = {}
    for sensor, paths in opened.source.point_cloud_paths.items():
        clouds[sensor] = tuple(
            adapter.load_cloud_from_source(opened.source, sensor, str(index + 1))
            for index in range(len(paths))
        )
    return FrameLoadPayload(
        source=opened.source,
        label=opened.label,
        label_origin=opened.label_origin,
        clouds=clouds,
        reference_layers=importer.load_reference_layers(opened.source),
    )
