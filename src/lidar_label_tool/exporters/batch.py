from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.exporters.base import LabelExporter


_SAFE_FRAME_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def export_frames(
    labels: Iterable[FrameLabel],
    exporter: LabelExporter,
    output_directory: Path,
) -> tuple[Path, ...]:
    """Export multiple frames as separate files without changing working labels."""
    output_root = Path(output_directory)
    exported: list[Path] = []
    seen: set[str] = set()
    for label in labels:
        if label.frame_id in seen:
            raise ValueError(f"duplicate frame_id in export: {label.frame_id}")
        if not _SAFE_FRAME_ID.fullmatch(label.frame_id) or label.frame_id in {".", ".."}:
            raise ValueError(f"unsafe frame_id in export: {label.frame_id}")
        seen.add(label.frame_id)
        target = output_root / f"{label.frame_id}{exporter.extension}"
        exporter.export_frame(label, target)
        exported.append(target)
    return tuple(exported)
