from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.ui.views import BevView, PointCloud3DView, SideView


@dataclass(slots=True)
class PointViewController:
    """Main-thread-only point-view fan-out, independent of label storage and frame I/O.

    Owns consistent object/point selection and gesture cancellation across 3D/BEV/side.
    Updating annotations never resets a camera pose or reloads original point arrays.
    """

    main: PointCloud3DView
    bev: BevView
    side: SideView

    def cancel_interactions(self) -> None:
        self.bev.cancel_interaction()
        self.side.cancel_interaction()

    def set_boxes(
        self, objects: Iterable[LabeledObject], selected_id: str | None,
        *, line_width: float, show_labels: bool, bev_visible: bool, side_visible: bool,
    ) -> None:
        snapshot = tuple(objects)
        self.main.set_boxes(snapshot, selected_id=selected_id, line_width=line_width, show_labels=show_labels)
        if bev_visible:
            self.bev.set_boxes(snapshot, selected_id=selected_id, line_width=line_width, show_labels=show_labels)
        if side_visible:
            self.side.set_boxes(snapshot, selected_id=selected_id, line_width=line_width)

    def set_selected_box(self, box: Box3D | None, *, bev_visible: bool, side_visible: bool) -> None:
        self.main.set_selected_box(box)
        if bev_visible:
            self.bev.set_selected_box(box)
        if side_visible:
            self.side.set_selected_box(box)
