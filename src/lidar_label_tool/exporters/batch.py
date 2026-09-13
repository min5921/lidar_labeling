from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.exporters.atomic_output import require_new_export_path
from lidar_label_tool.exporters.base import LabelExporter
from lidar_label_tool.services.background_task import TaskCancelled, TaskControl


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


class ExportBatchCancelled(TaskCancelled):
    def __init__(self, exported_paths: tuple[Path, ...]) -> None:
        self.exported_paths = exported_paths
        super().__init__(
            f"내보내기를 취소했습니다. 완료된 {len(exported_paths)}개 파일은 유지됩니다. "
            "원본/작업 라벨은 변경하지 않았습니다."
            + (f"\n출력 폴더: {exported_paths[0].parent}" if exported_paths else "")
        )


def export_frames(
    labels: Iterable[FrameLabel],
    exporter: LabelExporter,
    output_directory: Path,
    *,
    task: TaskControl | None = None,
) -> tuple[Path, ...]:
    """Export multiple frames as separate files without changing working labels."""
    output_root = Path(output_directory)
    task = task or TaskControl()
    labels = tuple(labels)
    exported: list[Path] = []
    seen: set[str] = set()
    for label in labels:
        task.check_cancelled()
        if label.frame_id.casefold() in seen:
            raise ValueError(f"duplicate frame_id in export: {label.frame_id}")
        if not _SAFE_FRAME_ID.fullmatch(label.frame_id) or label.frame_id in {".", ".."}:
            raise ValueError(f"unsafe frame_id in export: {label.frame_id}")
        seen.add(label.frame_id.casefold())
        exporter.validate(label)
        require_new_export_path(output_root / f"{label.frame_id}{exporter.extension}")
    for label in labels:
        target = output_root / f"{label.frame_id}{exporter.extension}"
        try:
            task.report("export", len(exported), len(labels), f"내보내기: {label.frame_id}")
            task.check_cancelled()
        except TaskCancelled as exc:
            raise ExportBatchCancelled(tuple(exported)) from exc
        try:
            exporter.export_frame(label, target)
        except (OSError, ValueError) as exc:
            raise ExportBatchError(label.frame_id, tuple(exported), exc) from exc
        exported.append(target)
    return tuple(exported)
