from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from lidar_label_tool.domain.labels import FrameLabel


@runtime_checkable
class LabelExporter(Protocol):
    """Extension point for explicit exports separate from working-label saves."""

    name: str
    extension: str

    def validate(self, label: FrameLabel) -> None: ...

    def export_frame(self, label: FrameLabel, output_path: Path) -> None: ...
