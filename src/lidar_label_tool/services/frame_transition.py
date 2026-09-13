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
    """Own one pending sequential transition and per-session ground opt-in, without Qt.

    Source points are shared read-only, while the selected object's metadata is copied.
    Cancellation always invalidates the worker request. Existing target IDs/recovery
    take precedence, and tracking is a second undo step after ordinary box carry.
    """

    target_frame_id: str | None = None
    objects: tuple[LabeledObject, ...] = ()
    selected_id: str | None = None
    tracking: TrackingRequest | None = None
    ground_object_ids: set[str] = field(default_factory=set)

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
        self.objects = created_objects(label.objects) if label is not None else ()
        self.selected_id = selected_id
        if label is None or selected is None or tracking_options is None:
            return
        if not any(obj.id == selected.id for obj in self.objects):
            self.objects += (selected,)
        self.tracking = TrackingRequest(
            label.dataset_id, label.frame_id, target_frame_id, label.reference_frame,
            tuple(sorted(label.point_cloud_paths)), deepcopy(selected), tuple(clouds), tracking_options,
        )

    def apply(
        self, history: AnnotationHistory, tracking: TrackingResult | None,
        *, enabled: bool, recovered: bool,
    ) -> CarryOutcome:
        label = history.current
        if recovered or not enabled or label.frame_id != self.target_frame_id or not self.objects:
            return CarryOutcome()
        merged, additions = merge_carried_objects(label, self.objects)
        history.apply(merged)
        message = ""
        if (
            tracking is not None and self.tracking is not None
            and tracking.target_frame_id == label.frame_id
            and tracking.object_id == self.tracking.obj.id
            and tracking.source_frame_id == self.tracking.source_frame_id
        ):
            message = tracking.message
            if tracking.object_id in additions:
                history.apply(apply_tracking_result(merged, tracking))
        selected = self.selected_id
        if selected not in {obj.id for obj in merged.objects}:
            selected = additions[0] if additions else None
        return CarryOutcome(additions, selected, message)
