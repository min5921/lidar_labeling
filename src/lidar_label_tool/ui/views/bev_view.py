from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box3d import bev_corners
from lidar_label_tool.ui.colors import class_color, point_rgba


_SELECTED = (255, 230, 15, 255)


def _brushes(rgba: np.ndarray) -> list[QBrush]:
    quantized = np.clip(np.rint(rgba * 255), 0, 255).astype(np.uint8)
    cache: dict[tuple[int, int, int, int], QBrush] = {}
    result: list[QBrush] = []
    for row in quantized:
        key = tuple(int(value) for value in row)
        brush = cache.get(key)
        if brush is None:
            brush = pg.mkBrush(key)
            cache[key] = brush
        result.append(brush)
    return result


class BevView(pg.PlotWidget):
    objectSelected = Signal(object)
    createBoxRequested = Signal(float, float)
    createBoxDragged = Signal(float, float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setBackground((18, 20, 24))
        self.setAspectLocked(True)
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "x forward", units="m")
        self.setLabel("left", "y left", units="m")
        self._point_items: list[object] = []
        self._box_items: list[object] = []
        self._first_cloud = True
        self._objects: tuple[LabeledObject, ...] = ()
        self.create_mode = False
        self._drag_start_data: tuple[float, float] | None = None
        self._drag_start_pixel: tuple[float, float] | None = None
        self._create_preview: object | None = None
        self.scene().sigMouseClicked.connect(self._mouse_clicked)

    def _clear_items(self, items: list[object]) -> None:
        for item in items:
            self.removeItem(item)
        items.clear()

    def set_clouds(
        self,
        clouds: Iterable[PointCloudData],
        *,
        max_points: int = 90_000,
        point_size: float = 2.0,
        color_mode: str = "sensor",
        uniform_color: str = "#E8E8E8",
    ) -> None:
        self._clear_items(self._point_items)
        clouds = tuple(clouds)
        total = sum(cloud.point_count for cloud in clouds)
        stride = max(1, math.ceil(total / max_points)) if total else 1
        for cloud in clouds:
            xyz = cloud.xyz[::stride]
            rgba = point_rgba(cloud, color_mode, uniform_color)[::stride]
            item = pg.ScatterPlotItem(
                x=xyz[:, 0],
                y=xyz[:, 1],
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
        show_labels: bool = True,
    ) -> None:
        self._clear_items(self._box_items)
        self._objects = tuple(objects)
        for obj in self._objects:
            corners = bev_corners(obj.box3d)
            closed = np.vstack((corners, corners[0]))
            selected = obj.id == selected_id
            width = max(line_width * 2.5, line_width + 2.0) if selected else line_width
            pen = pg.mkPen(
                _SELECTED if selected else class_color(obj.class_name), width=width
            )
            item = self.plot(closed[:, 0], closed[:, 1], pen=pen)
            self._box_items.append(item)
            if selected:
                marker = pg.ScatterPlotItem(
                    x=[obj.box3d.x], y=[obj.box3d.y], pen=None, brush=_SELECTED, size=12
                )
                self.addItem(marker)
                self._box_items.append(marker)
            if show_labels and (selected or len(self._objects) <= 15):
                name = str(obj.attributes.get("name") or f"{obj.class_name} · {obj.id[:6]}")
                text = pg.TextItem(
                    f"{name}\n{obj.box3d.length:.2f} × {obj.box3d.width:.2f} m",
                    color=_SELECTED if selected else class_color(obj.class_name),
                    anchor=(0.5, 1.1),
                )
                text.setPos(obj.box3d.x, obj.box3d.y)
                self.addItem(text)
                self._box_items.append(text)

    def focus_on_box(self, box: Box3D) -> None:
        radius = max(8.0, box.length * 2.5, box.width * 4.0)
        self.setXRange(box.x - radius, box.x + radius, padding=0)
        self.setYRange(box.y - radius, box.y + radius, padding=0)

    def set_create_mode(self, enabled: bool) -> None:
        self.create_mode = enabled
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        if not enabled:
            self._clear_create_preview()

    def mousePressEvent(self, event: Any) -> None:
        if self.create_mode and event.button() == Qt.MouseButton.LeftButton:
            point = self._event_data_point(event)
            self._drag_start_data = (float(point.x()), float(point.y()))
            position = event.position()
            self._drag_start_pixel = (float(position.x()), float(position.y()))
            self._update_create_preview(*self._drag_start_data)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self.create_mode and self._drag_start_data is not None:
            point = self._event_data_point(event)
            self._update_create_preview(float(point.x()), float(point.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if (
            self.create_mode
            and self._drag_start_data is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            point = self._event_data_point(event)
            end_x, end_y = float(point.x()), float(point.y())
            start_x, start_y = self._drag_start_data
            position = event.position()
            start_pixel = self._drag_start_pixel or (position.x(), position.y())
            pixel_distance = math.hypot(
                float(position.x()) - start_pixel[0],
                float(position.y()) - start_pixel[1],
            )
            length = abs(end_x - start_x)
            width = abs(end_y - start_y)
            self._clear_create_preview()
            if pixel_distance >= 8.0 and length >= 0.05 and width >= 0.05:
                self.createBoxDragged.emit(
                    (start_x + end_x) / 2.0,
                    (start_y + end_y) / 2.0,
                    length,
                    width,
                )
            else:
                self.createBoxRequested.emit(start_x, start_y)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _event_data_point(self, event: Any) -> object:
        scene_position = self.mapToScene(event.position().toPoint())
        return self.getViewBox().mapSceneToView(scene_position)

    def _update_create_preview(self, end_x: float, end_y: float) -> None:
        if self._drag_start_data is None:
            return
        start_x, start_y = self._drag_start_data
        x = [start_x, end_x, end_x, start_x, start_x]
        y = [start_y, start_y, end_y, end_y, start_y]
        if self._create_preview is None:
            self._create_preview = self.plot(
                x,
                y,
                pen=pg.mkPen(_SELECTED, width=2, style=Qt.PenStyle.DashLine),
            )
        else:
            self._create_preview.setData(x=x, y=y)

    def _clear_create_preview(self) -> None:
        if self._create_preview is not None:
            self.removeItem(self._create_preview)
        self._create_preview = None
        self._drag_start_data = None
        self._drag_start_pixel = None

    def _mouse_clicked(self, event: object) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.getViewBox().mapSceneToView(event.scenePos())
        x, y = float(point.x()), float(point.y())
        for obj in reversed(self._objects):
            cosine = math.cos(obj.box3d.yaw)
            sine = math.sin(obj.box3d.yaw)
            dx, dy = x - obj.box3d.x, y - obj.box3d.y
            local_x = cosine * dx + sine * dy
            local_y = -sine * dx + cosine * dy
            if abs(local_x) <= obj.box3d.length / 2 and abs(local_y) <= obj.box3d.width / 2:
                self.objectSelected.emit(obj.id)
                return
        if self.create_mode:
            self.createBoxRequested.emit(x, y)
        else:
            self.objectSelected.emit(None)
