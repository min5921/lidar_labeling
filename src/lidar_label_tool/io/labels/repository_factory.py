from __future__ import annotations

from pathlib import Path
from typing import Protocol

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.dataset import DatasetAdapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository


class WorkingLabelRepository(Protocol):
    annotation_dir: Path
    dataset_id: str

    def path_for(self, frame_id: str) -> Path: ...

    def exists(self, frame_id: str) -> bool: ...

    def load(self, frame_id: str) -> FrameLabel: ...

    def save(self, label: FrameLabel) -> FrameLabel: ...

    def load_backup(self, frame_id: str) -> FrameLabel: ...


def open_label_repository(
    adapter: DatasetAdapter,
    *,
    workspace_root: Path | None = None,
) -> WorkingLabelRepository:
    index = adapter.scan()
    if isinstance(adapter, DeviceCentricV2Adapter):
        return (
            V2LabelRepository.for_workspace(workspace_root, adapter)
            if workspace_root is not None
            else V2LabelRepository.for_sidecar(adapter)
        )
    return (
        LabelRepository.for_workspace(workspace_root, index.dataset_id)
        if workspace_root is not None
        else LabelRepository.for_sidecar(index.root, index.dataset_id)
    )
