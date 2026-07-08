from __future__ import annotations

from collections.abc import Collection
import math
import re

from lidar_label_tool.domain.labels import FrameLabel


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_label_for_export(
    label: FrameLabel,
    *,
    allowed_classes: Collection[str] | None = None,
    allow_unknown: bool = True,
) -> None:
    """Validate identity, classes and box geometry before any output path is touched."""
    for name, identity_value in (
        ("dataset_id", label.dataset_id),
        ("frame_id", label.frame_id),
    ):
        if (
            not identity_value
            or not _SAFE_COMPONENT.fullmatch(identity_value)
            or identity_value in {".", ".."}
        ):
            raise ValueError(f"export label has unsafe {name}: {identity_value!r}")
    known = set(allowed_classes) if allowed_classes is not None else None
    for obj in label.objects:
        if not obj.class_name:
            raise ValueError(f"object {obj.id!r} has an empty class_name")
        if known is not None and obj.class_name not in known:
            if not (allow_unknown and obj.class_name == "Unknown"):
                raise ValueError(
                    f"object {obj.id!r} has unknown class_name {obj.class_name!r}"
                )
        box = obj.box3d
        values: dict[str, float] = {
            "x": box.x,
            "y": box.y,
            "z": box.z,
            "length": box.length,
            "width": box.width,
            "height": box.height,
            "yaw": box.yaw,
        }
        for field, value in values.items():
            if not math.isfinite(value):
                raise ValueError(f"object {obj.id!r} box {field} must be finite")
        for field in ("length", "width", "height"):
            if values[field] <= 0:
                raise ValueError(f"object {obj.id!r} box {field} must be positive")
