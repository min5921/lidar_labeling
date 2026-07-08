from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Collection
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.exporters.validation import validate_label_for_export


class LidarLabelJsonExporter:
    """Export the current internal FrameLabel schema without reading source labels."""

    name = "lidar_label_json"
    extension = ".json"

    def __init__(
        self,
        allowed_classes: Collection[str] | None = None,
        *,
        allow_unknown: bool = True,
    ) -> None:
        self.allowed_classes = tuple(allowed_classes) if allowed_classes is not None else None
        self.allow_unknown = allow_unknown

    def validate(self, label: FrameLabel) -> None:
        validate_label_for_export(
            label,
            allowed_classes=self.allowed_classes,
            allow_unknown=self.allow_unknown,
        )

    def export_frame(self, label: FrameLabel, output_path: Path) -> None:
        self.validate(label)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    label.to_dict(), stream, ensure_ascii=False, indent=2, allow_nan=False
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            with temporary.open("r", encoding="utf-8") as stream:
                restored = FrameLabel.from_dict(json.load(stream))
            if restored.to_dict() != label.to_dict():
                raise ValueError("exported internal label failed round-trip validation")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
