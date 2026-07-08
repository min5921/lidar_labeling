from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box3d import bev_corners, box_contains_xy
from lidar_label_tool.geometry.box_edit import (
    move_box_xy,
    resize_box_from_corner,
    rotate_box_toward,
)
from lidar_label_tool.ui.colors import class_color
from lidar_label_tool.ui.render_cache import PointCloudRenderCache


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
    boxMoved = Signal(str, float, float)
    boxResized = Signal(str, float, float, float, float)
    boxRotated = Signal(str, float)

    def __init__(self, render_cache: PointCloudRenderCache | None = None) -> None:
        super().__init__()
        self._render_cache = render_cache or PointCloudRenderCache()
        self._cloud_render_token: tuple[object, ...] | None = None
        self.setBackground((18, 20, 24))
        self.setAspectLocked(True)
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "x forward", units="m")
        self.setLabel("left", "y left", units="m")
        self._point_items: list[object] = []
        self._box_items: list[object] = []
        self._first_cloud = True
        self._objects: tuple[LabeledObject, ...] = ()
        self._selected_id: str | None = None
        self.create_mode = False
        self._drag_start_data: tuple[float, float] | None = None
        self._drag_start_pixel: tuple[float, float] | None = None
        self._create_preview: object | None = None
        self._move_object: LabeledObject | None = None
        self._move_start_data: tuple[float, float] | None = None
        self._move_start_pixel: tuple[float, float] | None = None
        self._move_preview: object | None = None
        self._edit_mode: str | None = None
        self._resize_corner: int | None = None
        self._preview_box: Box3D | None = None
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
            item = pg.ScatterPlotItem(
                x=cloud.xyz[:, 0],
                y=cloud.xyz[:, 1],
                pen=None,
                brush=_brushes(cloud.rgba),
                size=point_size,
                pxMode=True,
            )
            self.addItem(item)
            self._point_items.append(item)
        if self._first_cloud and self._point_items:
            self.autoRange()
            self._first_cloud = False
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
        self._selected_id = selected_id
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
                handles = pg.ScatterPlotItem(
                    x=corners[:, 0],
                    y=corners[:, 1],
                    symbol="s",
                    pen=pg.mkPen(_SELECTED, width=2),
                    brush=pg.mkBrush(18, 20, 24, 230),
                    size=11,
                    pxMode=True,
                )
                self.addItem(handles)
                self._box_items.append(handles)
                front_x, front_y, rotate_x, rotate_y = self._rotate_handle_geometry(
                    obj.box3d
                )
                connector = self.plot(
                    [front_x, rotate_x],
                    [front_y, rotate_y],
                    pen=pg.mkPen(_SELECTED, width=2, style=Qt.PenStyle.DashLine),
                )
                rotate_handle = pg.ScatterPlotItem(
                    x=[rotate_x],
                    y=[rotate_y],
                    symbol="o",
                    pen=pg.mkPen(_SELECTED, width=2),
                    brush=pg.mkBrush(40, 235, 110, 230),
                    size=13,
                    pxMode=True,
                )
                self.addItem(rotate_handle)
                self._box_items.extend((connector, rotate_handle))
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
        self._clear_move_preview()
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
        if not self.create_mode and event.button() == Qt.MouseButton.LeftButton:
            point = self._event_data_point(event)
            selected = self._selected_object()
            if selected is not None:
                position = event.position()
                handle, corner = self._hit_selected_control(
                    selected.box3d, float(position.x()), float(position.y())
                )
                if handle is not None:
                    self._begin_box_edit(
                        selected,
                        handle,
                        corner,
                        float(point.x()),
                        float(point.y()),
                        float(position.x()),
                        float(position.y()),
                    )
                    event.accept()
                    return
            if selected is not None and box_contains_xy(
                selected.box3d, float(point.x()), float(point.y())
            ):
                position = event.position()
                self._begin_box_edit(
                    selected,
                    "move",
                    None,
                    float(point.x()),
                    float(point.y()),
                    float(position.x()),
                    float(position.y()),
                )
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self.create_mode and self._drag_start_data is not None:
            point = self._event_data_point(event)
            self._update_create_preview(float(point.x()), float(point.y()))
            event.accept()
            return
        if not self.create_mode and self._move_object is not None:
            point = self._event_data_point(event)
            self._update_edit_preview(float(point.x()), float(point.y()))
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
        if (
            not self.create_mode
            and self._move_object is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            point = self._event_data_point(event)
            end_x, end_y = float(point.x()), float(point.y())
            start_x, start_y = self._move_start_data or (end_x, end_y)
            position = event.position()
            start_pixel = self._move_start_pixel or (position.x(), position.y())
            pixel_distance = math.hypot(
                float(position.x()) - start_pixel[0],
                float(position.y()) - start_pixel[1],
            )
            moved_object = self._move_object
            mode = self._edit_mode
            preview_box = self._preview_box or self._box_for_pointer(end_x, end_y)
            self._clear_move_preview()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if pixel_distance >= 5.0 and preview_box is not None:
                if mode == "move":
                    self.boxMoved.emit(moved_object.id, preview_box.x, preview_box.y)
                elif mode == "resize":
                    self.boxResized.emit(
                        moved_object.id,
                        preview_box.x,
                        preview_box.y,
                        preview_box.length,
                        preview_box.width,
                    )
                elif mode == "rotate":
                    self.boxRotated.emit(moved_object.id, preview_box.yaw)
            else:
                self.objectSelected.emit(moved_object.id)
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

    def _begin_box_edit(
        self,
        selected: LabeledObject,
        mode: str,
        corner: int | None,
        data_x: float,
        data_y: float,
        pixel_x: float,
        pixel_y: float,
    ) -> None:
        self._move_object = selected
        self._move_start_data = (data_x, data_y)
        self._move_start_pixel = (pixel_x, pixel_y)
        self._edit_mode = mode
        self._resize_corner = corner
        self._preview_box = selected.box3d
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if mode in {"resize", "rotate"}
            else Qt.CursorShape.ClosedHandCursor
        )

    def _box_for_pointer(self, end_x: float, end_y: float) -> Box3D | None:
        if self._move_object is None or self._move_start_data is None:
            return None
        box = self._move_object.box3d
        if self._edit_mode == "move":
            start_x, start_y = self._move_start_data
            return move_box_xy(box, end_x - start_x, end_y - start_y)
        if self._edit_mode == "resize" and self._resize_corner is not None:
            return resize_box_from_corner(box, self._resize_corner, end_x, end_y)
        if self._edit_mode == "rotate":
            return rotate_box_toward(box, end_x, end_y)
        return None

    def _update_edit_preview(self, end_x: float, end_y: float) -> None:
        preview_box = self._box_for_pointer(end_x, end_y)
        if preview_box is None:
            return
        self._preview_box = preview_box
        corners = bev_corners(preview_box)
        closed = np.vstack((corners, corners[0]))
        if self._move_preview is None:
            self._move_preview = self.plot(
                closed[:, 0],
                closed[:, 1],
                pen=pg.mkPen(_SELECTED, width=3, style=Qt.PenStyle.DashLine),
            )
        else:
            self._move_preview.setData(x=closed[:, 0], y=closed[:, 1])

    def _clear_move_preview(self) -> None:
        if self._move_preview is not None:
            self.removeItem(self._move_preview)
        self._move_preview = None
        self._move_object = None
        self._move_start_data = None
        self._move_start_pixel = None
        self._edit_mode = None
        self._resize_corner = None
        self._preview_box = None

    def _selected_object(self) -> LabeledObject | None:
        return next((obj for obj in self._objects if obj.id == self._selected_id), None)

    def _hit_selected_control(
        self, box: Box3D, pixel_x: float, pixel_y: float
    ) -> tuple[str | None, int | None]:
        candidates: list[tuple[float, str, int | None]] = []
        center = self._data_to_widget(box.x, box.y)
        center_distance = math.hypot(pixel_x - center.x(), pixel_y - center.y())
        if center_distance <= 8.0:
            candidates.append((center_distance, "move", None))
        corners = bev_corners(box)
        for index, corner in enumerate(corners):
            handle = self._data_to_widget(float(corner[0]), float(corner[1]))
            distance = math.hypot(pixel_x - handle.x(), pixel_y - handle.y())
            if distance <= 10.0:
                candidates.append((distance, "resize", index))
        *_, rotate_x, rotate_y = self._rotate_handle_geometry(box)
        rotate = self._data_to_widget(rotate_x, rotate_y)
        rotate_distance = math.hypot(pixel_x - rotate.x(), pixel_y - rotate.y())
        if rotate_distance <= 11.0:
            candidates.append((rotate_distance, "rotate", None))
        if not candidates:
            return None, None
        _, mode, corner = min(candidates, key=lambda item: item[0])
        return mode, corner

    def _data_to_widget(self, x: float, y: float) -> object:
        scene = self.getViewBox().mapViewToScene(QPointF(x, y))
        return self.mapFromScene(scene)

    @staticmethod
    def _rotate_handle_geometry(box: Box3D) -> tuple[float, float, float, float]:
        cosine = math.cos(box.yaw)
        sine = math.sin(box.yaw)
        front_distance = box.length / 2.0
        offset = max(1.0, min(3.0, max(box.length, box.width) * 0.35))
        front_x = box.x + cosine * front_distance
        front_y = box.y + sine * front_distance
        return (
            front_x,
            front_y,
            box.x + cosine * (front_distance + offset),
            box.y + sine * (front_distance + offset),
        )

    def _mouse_clicked(self, event: object) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.getViewBox().mapSceneToView(event.scenePos())
        x, y = float(point.x()), float(point.y())
        for obj in reversed(self._objects):
            if box_contains_xy(obj.box3d, x, y):
                self.objectSelected.emit(obj.id)
                return
        if self.create_mode:
            self.createBoxRequested.emit(x, y)
        else:
            self.objectSelected.emit(None)
