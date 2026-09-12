from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel, LabeledObject, utc_now_iso
from lidar_label_tool.io.labels.object_source import (
    SavedLabelObjectLoader,
    SavedObjectSource,
    normalized_label_coordinates,
)


class ObjectTransferError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectTransferPlan:
    source: SavedObjectSource
    target: FrameLabel
    additions: tuple[LabeledObject, ...]
    skipped_ids: tuple[str, ...]


def plan_object_transfer(
    source: SavedObjectSource,
    target: FrameLabel,
    *,
    allowed_classes: Iterable[str],
    selected_ids: Iterable[str] | None = None,
) -> ObjectTransferPlan:
    """Plan explicit cross-dataset copying into the target frame's own identity."""
    if (
        source.reference_frame != target.reference_frame
        or source.lidar_ids != tuple(sorted(target.point_cloud_paths))
        or dict(source.coordinate_system) != normalized_label_coordinates(target.coordinate_system)
    ):
        raise ObjectTransferError(
            "LiDAR ID 또는 좌표계가 다릅니다. 같은 LiDAR·좌표계로 나눈 폴더 사이에서 사용하세요."
        )
    by_id = {obj.id: obj for obj in source.objects}
    requested = set(by_id) if selected_ids is None else set(selected_ids)
    if not requested <= by_id.keys():
        raise ObjectTransferError("이전 작업 라벨에 없는 객체가 선택되었습니다.")
    existing_ids = {obj.id for obj in target.objects}
    additions = tuple(
        obj for obj in source.objects if obj.id in requested and obj.id not in existing_ids
    )
    unknown_classes = {obj.class_name for obj in additions} - set(allowed_classes)
    if unknown_classes:
        raise ObjectTransferError(
            "현재 폴더에 없는 클래스입니다: " + ", ".join(sorted(unknown_classes))
            + ". 해당 객체를 선택 해제하거나 클래스 구성을 확인하세요."
        )
    for obj in additions:
        if not isinstance(obj.extra_fields.get("object_transfer_history", []), list):
            raise ObjectTransferError(f"{obj.id}: 기존 객체 가져오기 이력 형식이 올바르지 않습니다.")
    skipped = tuple(obj.id for obj in source.objects if obj.id in requested & existing_ids)
    return ObjectTransferPlan(source, target, additions, skipped)


def apply_object_transfer(plan: ObjectTransferPlan, current: FrameLabel) -> FrameLabel:
    """Apply one undoable edit; the caller saves through its existing repository."""
    if current != plan.target:
        raise ObjectTransferError("미리보기 이후 현재 프레임이 변경되었습니다. 다시 가져오세요.")
    SavedLabelObjectLoader.require_unchanged(plan.source)
    if not plan.additions:
        return current
    imported_at = utc_now_iso()
    additions: list[LabeledObject] = []
    for obj in plan.additions:
        copied = deepcopy(obj)
        fields = dict(copied.extra_fields)
        fields["object_transfer_history"] = [
            *fields.get("object_transfer_history", []),
            {
                "operation": "dataset_transfer",
                "source_dataset_id": plan.source.dataset_id,
                "source_profile_id": plan.source.profile_id,
                "source_frame_id": plan.source.frame_id,
                "source_object_id": obj.id,
                "source_label_name": plan.source.path.name,
                "source_label_sha256": plan.source.sha256,
                "imported_at_utc": imported_at,
            },
        ]
        additions.append(replace(copied, extra_fields=fields))
    return replace(current, objects=current.objects + tuple(additions), frame_status="in_progress")
