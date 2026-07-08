from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.exporters.base import LabelExporter


_SAFE_FRAME_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class ExportBatchError(RuntimeError):
    def __init__(
        self,
        frame_id: str,
        exported_paths: tuple[Path, ...],
        cause: Exception,
    ) -> None:
        super().__init__(
            f"export failed at frame {frame_id!r} after {len(exported_paths)} file(s): "
            f"{type(cause).__name__}: {cause}"
        )
        self.frame_id = frame_id
        self.exported_paths = exported_paths
        self.cause = cause


def export_frames(
    labels: Iterable[FrameLabel],
    exporter: LabelExporter,
    output_directory: Path,
) -> tuple[Path, ...]:
    """Export multiple frames as separate files without changing working labels."""
    output_root = Path(output_directory)
    labels = tuple(labels)
    exported: list[Path] = []
    seen: set[str] = set()
    for label in labels:
        if label.frame_id in seen:
            raise ValueError(f"duplicate frame_id in export: {label.frame_id}")
        if not _SAFE_FRAME_ID.fullmatch(label.frame_id) or label.frame_id in {".", ".."}:
            raise ValueError(f"unsafe frame_id in export: {label.frame_id}")
        seen.add(label.frame_id)
        exporter.validate(label)
    for label in labels:
        target = output_root / f"{label.frame_id}{exporter.extension}"
        try:
            exporter.export_frame(label, target)
        except (OSError, ValueError) as exc:
            raise ExportBatchError(label.frame_id, tuple(exported), exc) from exc
        exported.append(target)
    return tuple(exported)
