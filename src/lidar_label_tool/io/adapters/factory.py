from __future__ import annotations

from pathlib import Path

from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.dataset import DatasetAdapter


def open_dataset_adapter(root: Path, *, profile_id: str | None = None) -> DatasetAdapter:
    path = Path(root)
    if DeviceCentricV2Adapter.can_open(path):
        return DeviceCentricV2Adapter(path, profile_id=profile_id)
    if DeviceCentricAdapter.can_open(path):
        return DeviceCentricAdapter(path)
    if WaymoFrameCentricAdapter.can_open(path):
        return WaymoFrameCentricAdapter(path)
    raise ValueError(
        "unsupported dataset root: expected dataset.json or schema.json + segment.json"
    )
