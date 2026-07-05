from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel, LabeledObject


CREATED_BY_TOOL = "lidar_label_tool"


def created_objects(objects: Iterable[LabeledObject]) -> tuple[LabeledObject, ...]:
    """Return only objects explicitly created by this labeling tool."""
    return tuple(
        obj for obj in objects if obj.source.get("created_by") == CREATED_BY_TOOL
    )


def merge_carried_objects(
    target: FrameLabel,
    carried: Iterable[LabeledObject],
) -> tuple[FrameLabel, tuple[str, ...]]:
    """Append carried objects to a target frame without duplicating object IDs."""
    existing_ids = {obj.id for obj in target.objects}
    additions = tuple(obj for obj in carried if obj.id not in existing_ids)
    if not additions:
        return target, ()
    return (
        replace(
            target,
            objects=target.objects + additions,
            frame_status="in_progress",
        ),
        tuple(obj.id for obj in additions),
    )
