from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

from lidar_label_tool.domain.labels import FrameLabel, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.box_propagation import created_objects, merge_carried_objects
from lidar_label_tool.services.object_tracking import (
    TrackingOptions, TrackingRequest, TrackingResult, apply_tracking_result,
)


@dataclass(frozen=True, slots=True)
class CarryOutcome:
    object_ids: tuple[str, ...] = ()
    selected_id: str | None = None
    tracking_message: str = ""


@dataclass(slots=True)
class ForwardCarryState:
    """Own one pending transition and per-session object opt-ins, without Qt.

    Source points are shared read-only, while the selected object's metadata is copied.
    Cancellation always invalidates the worker request. Tracking carries only its
    selected object; ordinary carry keeps the explicit bulk mode. Existing target
    IDs/recovery take precedence unless the selected object opts into retracking.
    """

    target_frame_id: str | None = None
    objects: tuple[LabeledObject, ...] = ()
    selected_id: str | None = None
    tracking: TrackingRequest | None = None
    ground_object_ids: set[str] = field(default_factory=set)
    retrack_existing_ids: set[str] = field(default_factory=set)

    def clear(self) -> None:
        if self.tracking is not None:
            self.tracking.cancel.set()
        self.tracking = None
        self.target_frame_id = None
        self.objects = ()
        self.selected_id = None

    def prepare(
        self, label: FrameLabel | None, target_frame_id: str,
        selected: LabeledObject | None, selected_id: str | None,
        clouds: Iterable[PointCloudData], tracking_options: TrackingOptions | None,
    ) -> None:
        self.clear()
        self.target_frame_id = target_frame_id
        self.selected_id = selected_id
        if label is None:
            return
        if tracking_options is None:
            self.objects = created_objects(label.objects)
            return
        if selected is None:
            return
        snapshot = deepcopy(selected)
        self.objects = (snapshot,)
        self.tracking = TrackingRequest(
            label.dataset_id, label.frame_id, target_frame_id, label.reference_frame,
            tuple(sorted(label.point_cloud_paths)), snapshot, tuple(clouds), tracking_options,
        )

    def apply(
        self, history: AnnotationHistory, tracking: TrackingResult | None,
        *, enabled: bool, recovered: bool,
    ) -> CarryOutcome:
        label = history.current
        if recovered or not enabled or label.frame_id != self.target_frame_id or not self.objects:
            return CarryOutcome()
        tracking_matches = (
            tracking is not None and self.tracking is not None
            and tracking.target_frame_id == label.frame_id
            and tracking.object_id == self.tracking.obj.id
            and tracking.source_frame_id == self.tracking.source_frame_id
        )
        if tracking_matches and tracking is not None and tracking.expected_target_object is not None:
            current = next((obj for obj in label.objects if obj.id == tracking.object_id), None)
            if current != tracking.expected_target_object:
                return CarryOutcome(
                    selected_id=current.id if current is not None else None,
                    tracking_message="대상 라벨 상태가 변경되어 재추적 결과를 적용하지 않았습니다",
                )
        merged, additions = merge_carried_objects(label, self.objects)
        history.apply(merged)
        message = ""
        if tracking_matches and tracking is not None and self.tracking is not None:
            message = tracking.message
            if tracking.object_id in additions:
                history.apply(apply_tracking_result(merged, tracking))
            elif self.tracking.options.retrack_existing and tracking.expected_target_object is not None:
                updated = apply_tracking_result(merged, tracking, retrack_existing=True)
                history.apply(updated)
                if tracking.status == "matched" and updated is merged:
                    message = "대상 라벨 상태가 변경되어 재추적 결과를 적용하지 않았습니다"
        selected = self.selected_id
        if selected not in {obj.id for obj in merged.objects}:
            selected = additions[0] if additions else None
        return CarryOutcome(additions, selected, message)
