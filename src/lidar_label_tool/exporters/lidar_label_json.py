from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel


class LidarLabelJsonExporter:
    """Export the current internal FrameLabel schema without reading source labels."""

    name = "lidar_label_json"
    extension = ".json"

    def export_frame(self, label: FrameLabel, output_path: Path) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(label.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
