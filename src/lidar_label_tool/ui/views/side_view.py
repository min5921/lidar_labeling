from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pyqtgraph as pg

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box3d import side_rectangle
from lidar_label_tool.ui.colors import class_color, point_rgba
from lidar_label_tool.ui.views.bev_view import _brushes


_SELECTED = (255, 230, 15, 255)


class SideView(pg.PlotWidget):
    def __init__(self) -> None:
        super().__init__()
        self.plane = "xz"
        self.setBackground((18, 20, 24))
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "x forward", units="m")
        self.setLabel("left", "z up", units="m")
        self._point_items: list[object] = []
        self._box_items: list[object] = []
        self._first_cloud = True

    def _clear_items(self, items: list[object]) -> None:
        for item in items:
            self.removeItem(item)
        items.clear()

    def set_plane(self, plane: str) -> None:
        if plane not in {"xz", "yz"}:
            raise ValueError(plane)
        self.plane = plane
        self.setLabel("bottom", "x forward" if plane == "xz" else "y left", units="m")

    def set_clouds(
        self,
        clouds: Iterable[PointCloudData],
        *,
        max_points: int = 70_000,
        point_size: float = 2.0,
        color_mode: str = "sensor",
        uniform_color: str = "#E8E8E8",
    ) -> None:
        self._clear_items(self._point_items)
        clouds = tuple(clouds)
        total = sum(cloud.point_count for cloud in clouds)
        stride = max(1, math.ceil(total / max_points)) if total else 1
        axis = 0 if self.plane == "xz" else 1
        for cloud in clouds:
            xyz = cloud.xyz[::stride]
            rgba = point_rgba(cloud, color_mode, uniform_color)[::stride]
            item = pg.ScatterPlotItem(
                x=xyz[:, axis],
                y=xyz[:, 2],
                pen=None,
                brush=_brushes(rgba),
                size=point_size,
                pxMode=True,
            )
            self.addItem(item)
            self._point_items.append(item)
        if self._first_cloud and self._point_items:
            self.autoRange()
            self._first_cloud = False

    def set_boxes(
        self,
        objects: Iterable[LabeledObject],
        *,
        selected_id: str | None = None,
        line_width: float = 2.0,
    ) -> None:
        self._clear_items(self._box_items)
        for obj in objects:
            min_u, min_z, max_u, max_z = side_rectangle(obj.box3d, self.plane)
            selected = obj.id == selected_id
            width = max(line_width * 2.5, line_width + 2.0) if selected else line_width
            pen = pg.mkPen(
                _SELECTED if selected else class_color(obj.class_name), width=width
            )
            item = self.plot(
                [min_u, max_u, max_u, min_u, min_u],
                [min_z, min_z, max_z, max_z, min_z],
                pen=pen,
            )
            self._box_items.append(item)
            if selected:
                axis_value = obj.box3d.x if self.plane == "xz" else obj.box3d.y
                marker = pg.ScatterPlotItem(
                    x=[axis_value], y=[obj.box3d.z], pen=None, brush=_SELECTED, size=12
                )
                self.addItem(marker)
                self._box_items.append(marker)

    def focus_on_box(self, box: Box3D) -> None:
        center = box.x if self.plane == "xz" else box.y
        horizontal = max(8.0, box.length * 2.5, box.width * 4.0)
        vertical = max(4.0, box.height * 3.0)
        self.setXRange(center - horizontal, center + horizontal, padding=0)
        self.setYRange(box.z - vertical, box.z + vertical, padding=0)
