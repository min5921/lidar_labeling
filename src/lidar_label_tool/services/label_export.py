from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lidar_label_tool.exporters import create_default_registry, export_frames
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import FrameSessionService


@dataclass(frozen=True, slots=True)
class LabelExportResult:
    export_format: str
    dataset_id: str
    frame_count: int
    output: Path
    exported_paths: tuple[Path, ...]


def export_dataset_labels(
    dataset_root: Path,
    *,
    config: Mapping[str, Any],
    export_format: str,
    output: Path,
    frame_ids: Sequence[str] | None = None,
    workspace_root: Path | None = None,
) -> LabelExportResult:
    """Explicitly export labels without changing source or working labels."""
    root = Path(dataset_root).resolve()
    adapter = open_dataset_adapter(root)
    index = adapter.scan()
    repository = (
        LabelRepository.for_workspace(workspace_root, index.dataset_id)
        if workspace_root is not None
        else LabelRepository.for_sidecar(root, index.dataset_id)
    )
    importer = WaymoLabelImporter(
        config["source_class_mappings"],
        source_format=(
            "device_centric_json"
            if isinstance(adapter, DeviceCentricAdapter)
            else "waymo_frame_json"
        ),
    )
    session = FrameSessionService(adapter, importer, repository)
    selected = tuple(frame_ids) if frame_ids else index.frame_ids
    unknown = sorted(set(selected) - set(index.frame_ids))
    if unknown:
        raise ValueError(f"unknown frame id(s): {', '.join(unknown)}")
    labels = tuple(session.open_frame(frame_id).label for frame_id in selected)
    allowed_classes = tuple(str(item["name"]) for item in config["classes"])
    exporter = create_default_registry(allowed_classes).get(export_format)
    target = Path(output).resolve()
    if len(labels) == 1 and target.suffix:
        exporter.export_frame(labels[0], target)
        exported = (target,)
    else:
        if len(labels) > 1 and target.suffix and not target.is_dir():
            raise ValueError("multiple-frame output must be a directory, not a JSON path")
        if target.exists() and not target.is_dir():
            raise ValueError("multiple-frame output must be a directory")
        exported = export_frames(labels, exporter, target)
    return LabelExportResult(
        export_format=exporter.name,
        dataset_id=index.dataset_id,
        frame_count=len(exported),
        output=target,
        exported_paths=exported,
    )
