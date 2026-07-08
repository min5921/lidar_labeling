from __future__ import annotations

import math
from typing import Any, Iterable

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box3d import side_rectangle
from lidar_label_tool.geometry.box_edit import move_box_z, resize_box_height
from lidar_label_tool.ui.colors import class_color
from lidar_label_tool.ui.render_cache import PointCloudRenderCache
from lidar_label_tool.ui.views.bev_view import _brushes


_SELECTED = (255, 230, 15, 255)


class SideView(pg.PlotWidget):
    boxVerticalMoved = Signal(str, float)
    boxHeightResized = Signal(str, float, float)

    def __init__(self, render_cache: PointCloudRenderCache | None = None) -> None:
        super().__init__()
        self._render_cache = render_cache or PointCloudRenderCache()
        self._cloud_render_token: tuple[object, ...] | None = None
        self.plane = "xz"
        self.setBackground((18, 20, 24))
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel("bottom", "x forward", units="m")
        self.setLabel("left", "z up", units="m")
        self._point_items: list[object] = []
        self._box_items: list[object] = []
        self._first_cloud = True
        self._objects: tuple[LabeledObject, ...] = ()
        self._selected_id: str | None = None
        self._edit_object: LabeledObject | None = None
        self._edit_mode: str | None = None
        self._edit_start_data: tuple[float, float] | None = None
        self._edit_start_pixel: tuple[float, float] | None = None
        self._preview_item: object | None = None
        self._preview_box: Box3D | None = None

    def _clear_items(self, items: list[object]) -> None:
        for item in items:
            self.removeItem(item)
        items.clear()

    def set_plane(self, plane: str) -> None:
        if plane not in {"xz", "yz"}:
            raise ValueError(plane)
        self._clear_edit_preview()
        self.plane = plane
        self._cloud_render_token = None
        self.setLabel("bottom", "x forward" if plane == "xz" else "y left", units="m")

    def set_clouds(
        self,
        clouds: Iterable[PointCloudData],
        *,
        max_points: int = 70_000,
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
        token = (batch.token, float(point_size), self.plane)
        if token == self._cloud_render_token:
            return batch.rendered_point_count
        self._clear_items(self._point_items)
        axis = 0 if self.plane == "xz" else 1
        for cloud in batch.clouds:
            item = pg.ScatterPlotItem(
                x=cloud.xyz[:, axis],
                y=cloud.xyz[:, 2],
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
    ) -> None:
        self._clear_items(self._box_items)
        self._objects = tuple(objects)
        self._selected_id = selected_id
        for obj in self._objects:
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
                handles = pg.ScatterPlotItem(
                    x=[axis_value, axis_value],
                    y=[min_z, max_z],
                    symbol="s",
                    pen=pg.mkPen(_SELECTED, width=2),
                    brush=pg.mkBrush(18, 20, 24, 230),
                    size=12,
                    pxMode=True,
                )
                self.addItem(handles)
                self._box_items.append(handles)

    def focus_on_box(self, box: Box3D) -> None:
        center = box.x if self.plane == "xz" else box.y
        horizontal = max(8.0, box.length * 2.5, box.width * 4.0)
        vertical = max(4.0, box.height * 3.0)
        self.setXRange(center - horizontal, center + horizontal, padding=0)
        self.setYRange(box.z - vertical, box.z + vertical, padding=0)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            selected = self._selected_object()
            if selected is not None:
                point = self._event_data_point(event)
                position = event.position()
                mode = self._hit_selected_handle(
                    selected.box3d, float(position.x()), float(position.y())
                )
                min_u, min_z, max_u, max_z = side_rectangle(
                    selected.box3d, self.plane
                )
                inside = (
                    min_u <= float(point.x()) <= max_u
                    and min_z <= float(point.y()) <= max_z
                )
                if mode is not None or inside:
                    self._edit_object = selected
                    self._edit_mode = mode or "move"
                    self._edit_start_data = (float(point.x()), float(point.y()))
                    self._edit_start_pixel = (
                        float(position.x()),
                        float(position.y()),
                    )
                    self._preview_box = selected.box3d
                    self.setCursor(
                        Qt.CursorShape.SizeVerCursor
                        if self._edit_mode in {"move", "top", "bottom"}
                        else Qt.CursorShape.ArrowCursor
                    )
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._edit_object is not None:
            point = self._event_data_point(event)
            self._update_edit_preview(float(point.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._edit_object is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._event_data_point(event)
            end_z = float(point.y())
            position = event.position()
            start_pixel = self._edit_start_pixel or (position.x(), position.y())
            pixel_distance = math.hypot(
                float(position.x()) - start_pixel[0],
                float(position.y()) - start_pixel[1],
            )
            edited_object = self._edit_object
            mode = self._edit_mode
            preview_box = self._preview_box or self._box_for_z(end_z)
            self._clear_edit_preview()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if pixel_distance >= 5.0 and preview_box is not None:
                if mode == "move":
                    self.boxVerticalMoved.emit(edited_object.id, preview_box.z)
                elif mode in {"top", "bottom"}:
                    self.boxHeightResized.emit(
                        edited_object.id, preview_box.z, preview_box.height
                    )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _selected_object(self) -> LabeledObject | None:
        return next((obj for obj in self._objects if obj.id == self._selected_id), None)

    def _event_data_point(self, event: Any) -> object:
        scene_position = self.mapToScene(event.position().toPoint())
        return self.getViewBox().mapSceneToView(scene_position)

    def _hit_selected_handle(
        self, box: Box3D, pixel_x: float, pixel_y: float
    ) -> str | None:
        axis_value = box.x if self.plane == "xz" else box.y
        candidates: list[tuple[float, str]] = []
        center = self._data_to_widget(axis_value, box.z)
        center_distance = math.hypot(pixel_x - center.x(), pixel_y - center.y())
        if center_distance <= 8.0:
            candidates.append((center_distance, "move"))
        bottom = self._data_to_widget(axis_value, box.z - box.height / 2.0)
        top = self._data_to_widget(axis_value, box.z + box.height / 2.0)
        top_distance = math.hypot(pixel_x - top.x(), pixel_y - top.y())
        bottom_distance = math.hypot(pixel_x - bottom.x(), pixel_y - bottom.y())
        if top_distance <= 11.0:
            candidates.append((top_distance, "top"))
        if bottom_distance <= 11.0:
            candidates.append((bottom_distance, "bottom"))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def _data_to_widget(self, x: float, z: float) -> object:
        scene = self.getViewBox().mapViewToScene(QPointF(x, z))
        return self.mapFromScene(scene)

    def _box_for_z(self, end_z: float) -> Box3D | None:
        if self._edit_object is None or self._edit_start_data is None:
            return None
        box = self._edit_object.box3d
        if self._edit_mode == "move":
            return move_box_z(box, end_z - self._edit_start_data[1])
        if self._edit_mode in {"top", "bottom"}:
            return resize_box_height(box, self._edit_mode, end_z)
        return None

    def _update_edit_preview(self, end_z: float) -> None:
        preview_box = self._box_for_z(end_z)
        if preview_box is None:
            return
        self._preview_box = preview_box
        min_u, min_z, max_u, max_z = side_rectangle(preview_box, self.plane)
        x = [min_u, max_u, max_u, min_u, min_u]
        z = [min_z, min_z, max_z, max_z, min_z]
        if self._preview_item is None:
            self._preview_item = self.plot(
                x,
                z,
                pen=pg.mkPen(_SELECTED, width=3, style=Qt.PenStyle.DashLine),
            )
        else:
            self._preview_item.setData(x=x, y=z)

    def _clear_edit_preview(self) -> None:
        if self._preview_item is not None:
            self.removeItem(self._preview_item)
        self._preview_item = None
        self._edit_object = None
        self._edit_mode = None
        self._edit_start_data = None
        self._edit_start_pixel = None
        self._preview_box = None
