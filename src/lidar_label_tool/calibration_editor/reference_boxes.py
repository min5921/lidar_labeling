from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable
from uuid import uuid4

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import fit_box_bottom_to_points


@dataclass(slots=True)
class CalibrationReferenceBoxes:
    """Session-only 3D boxes used to visually verify camera calibration.

    The boxes are keyed by frame and deliberately expose no serialization API.
    They must never be inserted into a source or working :class:`FrameLabel`.
    Coordinates use the dataset reference frame in meter: x forward, y left,
    z up, with yaw in radians around +z.
    """

    _by_frame: dict[str, tuple[LabeledObject, ...]] = field(default_factory=dict)

    def for_frame(self, frame_id: str) -> tuple[LabeledObject, ...]:
        return self._by_frame.get(frame_id, ())

    def find(self, frame_id: str, object_id: str | None) -> LabeledObject | None:
        if object_id is None:
            return None
        return next(
            (obj for obj in self.for_frame(frame_id) if obj.id == object_id),
            None,
        )

    def create(
        self,
        frame_id: str,
        *,
        class_name: str,
        x: float,
        y: float,
        length: float,
        width: float,
        height: float,
        clouds: Iterable[PointCloudData] = (),
    ) -> LabeledObject:
        if not frame_id:
            raise ValueError("frame_id must not be empty")
        initial_box = Box3D(
            x=x,
            y=y,
            z=height / 2.0,
            length=length,
            width=width,
            height=height,
            yaw=0.0,
        )
        fitted_box = fit_box_bottom_to_points(initial_box, clouds)
        box = fitted_box if fitted_box is not None else initial_box
        frame_boxes = self.for_frame(frame_id)
        created = LabeledObject(
            id=f"calibration-reference-{uuid4().hex}",
            class_name=class_name,
            box3d=box,
            attributes={"name": f"Calibration 기준 {len(frame_boxes) + 1}"},
            source={
                "created_by": "calibration_editor",
                "temporary": True,
                "z_initialization": (
                    "point_floor" if fitted_box is not None else "default_floor_zero"
                ),
            },
        )
        self._by_frame[frame_id] = frame_boxes + (created,)
        return created

    def replace_box(
        self,
        frame_id: str,
        object_id: str,
        box: Box3D,
    ) -> LabeledObject:
        current = self.find(frame_id, object_id)
        if current is None:
            raise KeyError(object_id)
        updated = replace(current, box3d=box)
        self._by_frame[frame_id] = tuple(
            updated if obj.id == object_id else obj
            for obj in self.for_frame(frame_id)
        )
        return updated

    def fit_to_points(
        self,
        frame_id: str,
        object_id: str,
        clouds: Iterable[PointCloudData],
    ) -> LabeledObject | None:
        current = self.find(frame_id, object_id)
        if current is None:
            raise KeyError(object_id)
        fitted = fit_box_bottom_to_points(current.box3d, clouds)
        if fitted is None:
            return None
        return self.replace_box(frame_id, object_id, fitted)

    def delete(self, frame_id: str, object_id: str) -> bool:
        current = self.for_frame(frame_id)
        remaining = tuple(obj for obj in current if obj.id != object_id)
        if len(remaining) == len(current):
            return False
        if remaining:
            self._by_frame[frame_id] = remaining
        else:
            self._by_frame.pop(frame_id, None)
        return True

    def clear(self, frame_id: str) -> int:
        removed = len(self.for_frame(frame_id))
        self._by_frame.pop(frame_id, None)
        return removed
