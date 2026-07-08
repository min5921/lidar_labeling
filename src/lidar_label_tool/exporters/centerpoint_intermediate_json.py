from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel


class CenterPointIntermediateJsonExporter:
    """Simple per-frame interchange JSON, not an official training dataset format."""

    name = "centerpoint_intermediate_json"
    extension = ".json"

    def export_frame(self, label: FrameLabel, output_path: Path) -> None:
        payload = {
            "format": self.name,
            "schema_version": "1.0",
            "format_notice": (
                "Intermediate LiDAR boxes only; convert to the exact target training "
                "dataset format before use."
            ),
            "dataset_id": label.dataset_id,
            "frame_id": label.frame_id,
            "reference_frame": label.reference_frame,
            "coordinate_system": dict(label.coordinate_system),
            "yaw_unit": "radians",
            "objects": [
                {
                    "object_id": obj.id,
                    "class_name": obj.class_name,
                    "box3d": {
                        "center": {
                            "x": obj.box3d.x,
                            "y": obj.box3d.y,
                            "z": obj.box3d.z,
                        },
                        "size": {
                            "length": obj.box3d.length,
                            "width": obj.box3d.width,
                            "height": obj.box3d.height,
                        },
                        "yaw": obj.box3d.yaw,
                    },
                }
                for obj in label.objects
            ],
        }
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
