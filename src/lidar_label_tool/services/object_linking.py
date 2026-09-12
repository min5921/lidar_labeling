from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from lidar_label_tool.domain.labels import FrameLabel, LabeledObject, utc_now_iso


class ObjectLinkError(ValueError):
    """A requested cross-frame object edit cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class ObjectLinkReference:
    dataset_id: str
    profile_id: str | None
    reference_frame: str
    lidar_ids: tuple[str, ...]
    frame_id: str
    obj: LabeledObject


def remember_object(
    label: FrameLabel, object_id: str, *, profile_id: str | None
) -> ObjectLinkReference:
    """Snapshot one object for explicit copying or ID linking within a profile."""
    obj = _find_object(label, object_id)
    return ObjectLinkReference(
        dataset_id=label.dataset_id,
        profile_id=profile_id,
        reference_frame=label.reference_frame,
        lidar_ids=tuple(sorted(label.point_cloud_paths)),
        frame_id=label.frame_id,
        obj=deepcopy(obj),
    )


def copy_reference_object(
    target: FrameLabel, reference: ObjectLinkReference, *, profile_id: str | None
) -> FrameLabel:
    """Copy one remembered box into the current frame without overwriting an ID."""
    _require_scope(target, reference, profile_id)
    _require_available_id(target, reference.obj.id)
    copied = _with_link_history(reference.obj, reference, operation="copy")
    return replace(target, objects=target.objects + (copied,), frame_status="in_progress")


def link_object_to_reference(
    target: FrameLabel,
    object_id: str,
    reference: ObjectLinkReference,
    *,
    profile_id: str | None,
) -> FrameLabel:
    """Change only the selected object's ID and append an auditable link record."""
    _require_scope(target, reference, profile_id)
    selected = _find_object(target, object_id)
    if selected.id == reference.obj.id:
        return target
    if target.frame_id == reference.frame_id:
        raise ObjectLinkError("기준 객체와 다른 프레임으로 이동한 뒤 연결하세요.")
    _require_available_id(target, reference.obj.id)
    if selected.class_name != reference.obj.class_name:
        raise ObjectLinkError("두 객체의 클래스가 다릅니다. 같은 객체인지 확인하고 클래스를 맞추세요.")
    linked = _with_link_history(selected, reference, operation="link")
    linked = replace(linked, id=reference.obj.id)
    return replace(
        target,
        objects=tuple(linked if obj.id == object_id else obj for obj in target.objects),
        frame_status="in_progress",
    )


def _find_object(label: FrameLabel, object_id: str) -> LabeledObject:
    obj = next((obj for obj in label.objects if obj.id == object_id), None)
    if obj is None:
        raise ObjectLinkError("현재 프레임에서 연결할 객체를 먼저 선택하세요.")
    return obj


def _require_scope(
    target: FrameLabel, reference: ObjectLinkReference, profile_id: str | None
) -> None:
    if (
        target.dataset_id != reference.dataset_id
        or profile_id != reference.profile_id
        or target.reference_frame != reference.reference_frame
        or tuple(sorted(target.point_cloud_paths)) != reference.lidar_ids
    ):
        raise ObjectLinkError("같은 데이터셋·profile·LiDAR 좌표계 안에서만 객체를 연결할 수 있습니다.")


def _require_available_id(target: FrameLabel, object_id: str) -> None:
    if any(obj.id == object_id for obj in target.objects):
        raise ObjectLinkError("현재 프레임에 기준 ID의 객체가 이미 있습니다. 그 객체를 선택해 편집하세요.")


def _with_link_history(
    obj: LabeledObject, reference: ObjectLinkReference, *, operation: str
) -> LabeledObject:
    # Preserve imported IDs in source metadata and retain every prior manual link.
    fields = deepcopy(dict(obj.extra_fields))
    history = fields.get("object_link_history", [])
    if not isinstance(history, list):
        raise ObjectLinkError("기존 object_link_history 형식이 올바르지 않아 연결을 적용하지 않았습니다.")
    fields["object_link_history"] = [
        *history,
        {
            "operation": operation,
            "previous_object_id": obj.id,
            "reference_object_id": reference.obj.id,
            "reference_frame_id": reference.frame_id,
            "linked_at_utc": utc_now_iso(),
        },
    ]
    return replace(obj, extra_fields=fields)
