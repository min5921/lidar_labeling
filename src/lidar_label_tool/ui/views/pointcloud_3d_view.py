from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pyqtgraph.opengl as gl
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QVector3D
from PySide6.QtWidgets import QLabel

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box3d import box_corners_3d
from lidar_label_tool.ui.colors import class_color
from lidar_label_tool.ui.render_cache import PointCloudRenderCache


_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)
_SELECTED_COLOR = (1.0, 0.9, 0.05, 1.0)


class PointCloud3DView(gl.GLViewWidget):
    objectSelected = Signal(object)

    def __init__(self, render_cache: PointCloudRenderCache | None = None) -> None:
        super().__init__()
        self._render_cache = render_cache or PointCloudRenderCache()
        self._cloud_render_token: tuple[object, ...] | None = None
        self.setBackgroundColor((18, 20, 24))
        self.setCameraPosition(distance=45, elevation=28, azimuth=-90)
        self._point_items: list[object] = []
        self._box_items: list[object] = []
        self._objects: tuple[LabeledObject, ...] = ()
        self._mouse_press_position: tuple[float, float] | None = None
        self._selected_tag_object: LabeledObject | None = None
        self._selection_tag = QLabel(self)
        self._selection_tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._selection_tag.setStyleSheet(
            "color:#111827; background:#FFE60F; border:1px solid #111827; "
            "border-radius:3px; padding:2px 4px; font-weight:600;"
        )
        self._selection_tag.hide()
        grid = gl.GLGridItem()
        grid.setSize(100, 100)
        grid.setSpacing(5, 5)
        self.addItem(grid)
        axis = gl.GLAxisItem()
        axis.setSize(5, 5, 5)
        self.addItem(axis)

    def _clear_items(self, items: list[object]) -> None:
        for item in items:
            self.removeItem(item)
        items.clear()

    def set_clouds(
        self,
        clouds: Iterable[PointCloudData],
        *,
        max_points: int = 250_000,
        point_size: float = 2.0,
        color_mode: str = "sensor",
        uniform_color: str = "#E8E8E8",
    ) -> int:
        batch = self._render_cache.prepare(
            clouds,
            max_points=max_points,
            color_mode=color_mode,
            uniform_color=uniform_color,
        )
        token = (batch.token, float(point_size))
        if token == self._cloud_render_token:
            return batch.rendered_point_count
        self._clear_items(self._point_items)
        for cloud in batch.clouds:
            item = gl.GLScatterPlotItem(
                pos=cloud.xyz,
                color=cloud.rgba,
                size=point_size,
                pxMode=True,
            )
            self.addItem(item)
            self._point_items.append(item)
        self._cloud_render_token = token
        return batch.rendered_point_count

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
        self._selected_tag_object = None
        for obj in self._objects:
            corners = box_corners_3d(obj.box3d).astype(np.float32)
            positions = np.vstack([corners[index] for edge in _BOX_EDGES for index in edge])
            selected = obj.id == selected_id
            if selected and show_labels:
                self._selected_tag_object = obj
            if selected:
                color = _SELECTED_COLOR
                width = max(line_width * 2.5, line_width + 2.0)
            else:
                rgb = class_color(obj.class_name)
                color = tuple(channel / 255.0 for channel in rgb) + (0.78,)
                width = line_width
            line = gl.GLLinePlotItem(pos=positions, color=color, width=width, mode="lines")
            self.addItem(line)
            self._box_items.append(line)
            if selected:
                marker = gl.GLScatterPlotItem(
                    pos=np.array([[obj.box3d.x, obj.box3d.y, obj.box3d.z]], dtype=np.float32),
                    color=_SELECTED_COLOR,
                    size=14.0,
                    pxMode=True,
                )
                self.addItem(marker)
                self._box_items.append(marker)
            if show_labels and not selected and len(self._objects) <= 15:
                name = str(obj.attributes.get("name") or f"{obj.class_name} · {obj.id[:6]}")
                tag = gl.GLTextItem(
                    pos=(
                        obj.box3d.x,
                        obj.box3d.y,
                        obj.box3d.z + obj.box3d.height / 2.0 + 0.2,
                    ),
                    color=(255, 230, 15, 255) if selected else (*class_color(obj.class_name), 230),
                    text=name,
                    font=QFont("Arial", 10),
                )
                self.addItem(tag)
                self._box_items.append(tag)
        if self._selected_tag_object is None:
            self._selection_tag.hide()
        else:
            obj = self._selected_tag_object
            self._selection_tag.setText(
                str(obj.attributes.get("name") or f"{obj.class_name} · {obj.id[:6]}")
            )
            self._selection_tag.adjustSize()
            self._position_selection_tag()

    def focus_on_box(self, box: Box3D) -> None:
        self.setCameraPosition(
            pos=QVector3D(box.x, box.y, box.z),
            distance=max(15.0, box.length * 5),
        )

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position()
            self._mouse_press_position = (float(position.x()), float(position.y()))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        position = event.position()
        is_click = False
        if event.button() == Qt.MouseButton.LeftButton and self._mouse_press_position is not None:
            is_click = math.hypot(
                float(position.x()) - self._mouse_press_position[0],
                float(position.y()) - self._mouse_press_position[1],
            ) <= 5.0
        super().mouseReleaseEvent(event)
        if is_click:
            self.objectSelected.emit(
                self._pick_object(float(position.x()), float(position.y()))
            )
        self._mouse_press_position = None

    def mouseMoveEvent(self, event: Any) -> None:
        super().mouseMoveEvent(event)
        self._position_selection_tag()

    def wheelEvent(self, event: Any) -> None:
        super().wheelEvent(event)
        self._position_selection_tag()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._position_selection_tag()

    def _position_selection_tag(self) -> None:
        obj = self._selected_tag_object
        if obj is None or self.width() <= 0 or self.height() <= 0:
            self._selection_tag.hide()
            return
        world = QVector3D(
            obj.box3d.x,
            obj.box3d.y,
            obj.box3d.z + obj.box3d.height / 2.0 + 0.2,
        )
        view_matrix = self.viewMatrix()
        if view_matrix.map(world).z() >= -1e-6:
            self._selection_tag.hide()
            return
        viewport = self.getViewport()
        projected = (self.projectionMatrix(viewport, viewport) * view_matrix).map(world)
        if not (-1.0 <= projected.x() <= 1.0 and -1.0 <= projected.y() <= 1.0):
            self._selection_tag.hide()
            return
        x = (projected.x() + 1.0) * self.width() / 2.0
        y = (1.0 - projected.y()) * self.height() / 2.0
        self._selection_tag.move(
            int(
                max(
                    0.0,
                    min(
                        self.width() - self._selection_tag.width(),
                        x - self._selection_tag.width() / 2.0,
                    ),
                )
            ),
            int(
                max(
                    0.0,
                    min(
                        self.height() - self._selection_tag.height(),
                        y - self._selection_tag.height() - 5.0,
                    ),
                )
            ),
        )
        self._selection_tag.show()

    def _pick_object(self, mouse_x: float, mouse_y: float) -> str | None:
        """Pick the smallest projected 3D box containing a widget-space click."""
        if not self._objects or self.width() <= 0 or self.height() <= 0:
            return None
        viewport = self.getViewport()
        view_matrix = self.viewMatrix()
        matrix = self.projectionMatrix(viewport, viewport) * view_matrix
        candidates: list[tuple[float, float, str]] = []
        for obj in self._objects:
            screen_points: list[tuple[float, float, float]] = []
            for corner in box_corners_3d(obj.box3d):
                world = QVector3D(
                    float(corner[0]), float(corner[1]), float(corner[2])
                )
                eye = view_matrix.map(world)
                if eye.z() >= -1e-6:
                    continue
                projected = matrix.map(world)
                ndc_x = projected.x()
                ndc_y = projected.y()
                ndc_z = projected.z()
                if -1.2 <= ndc_z <= 1.2:
                    screen_points.append(
                        (
                            (ndc_x + 1.0) * self.width() / 2.0,
                            (1.0 - ndc_y) * self.height() / 2.0,
                            ndc_z,
                        )
                    )
            if len(screen_points) < 2:
                continue
            xs = [point[0] for point in screen_points]
            ys = [point[1] for point in screen_points]
            left, right = max(0.0, min(xs)), min(float(self.width()), max(xs))
            top, bottom = max(0.0, min(ys)), min(float(self.height()), max(ys))
            margin = 6.0
            if (
                left - margin <= mouse_x <= right + margin
                and top - margin <= mouse_y <= bottom + margin
            ):
                area = max(1.0, (right - left) * (bottom - top))
                depth = sum(point[2] for point in screen_points) / len(screen_points)
                candidates.append((area, depth, obj.id))
        return min(candidates)[2] if candidates else None
