from __future__ import annotations

from dataclasses import dataclass

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.io.dataset import DatasetAdapter, SourceFrameData
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter


@dataclass(frozen=True, slots=True)
class OpenedFrame:
    source: SourceFrameData
    label: FrameLabel
    label_origin: str


class FrameSessionService:
    def __init__(
        self,
        adapter: DatasetAdapter,
        importer: WaymoLabelImporter,
        repository: LabelRepository | None = None,
    ) -> None:
        self.adapter = adapter
        self.importer = importer
        self.repository = repository

    def open_frame(self, frame_id: str) -> OpenedFrame:
        source = self.adapter.load_source_frame(frame_id)
        if self.repository is not None and self.repository.exists(frame_id):
            return OpenedFrame(source, self.repository.load(frame_id), "working")
        return OpenedFrame(source, self.importer.import_laser_labels(source), "source")

    def save(self, label: FrameLabel) -> FrameLabel:
        if self.repository is None:
            raise RuntimeError("no working label repository configured")
        return self.repository.save(label)
