from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from lidar_label_tool.calibration.waymo_camera import ProjectedWireframe


class CameraImageView(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QColor(18, 20, 24))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._selected_rect: QRectF | None = None
        self._focus_selected = False

    def set_image(
        self,
        path: Path,
        camera_labels: Iterable[Mapping[str, Any]] = (),
        projected_labels: Iterable[Mapping[str, Any]] = (),
        live_wireframes: Iterable[ProjectedWireframe] = (),
        *,
        selected_object_id: str | None = None,
        camera_id: str = "",
        focus_selected: bool = False,
        box_line_width: float = 2.0,
    ) -> bool:
        self._scene.clear()
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError(f"failed to load image: {path}")
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._selected_rect = None
        self._focus_selected = focus_selected
        self._draw_boxes(camera_labels, QColor(255, 176, 32, 210), box_line_width)
        source_selected_rect = self._draw_projected_boxes(
            projected_labels, selected_object_id, camera_id, box_line_width
        )
        live_selected_rect = self._draw_live_wireframes(
            live_wireframes, selected_object_id, box_line_width
        )
        self._selected_rect = live_selected_rect or source_selected_rect
        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        self._fit()
        return self._selected_rect is not None

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._selected_rect = None

    def _draw_boxes(
        self, labels: Iterable[Mapping[str, Any]], color: QColor, width: float
    ) -> None:
        pen = QPen(color, width)
        for label in labels:
            rectangle = self._rectangle(label)
            if rectangle is not None:
                self._scene.addRect(rectangle, pen)

    def _draw_projected_boxes(
        self,
        labels: Iterable[Mapping[str, Any]],
        selected_object_id: str | None,
        camera_id: str,
        line_width: float,
    ) -> QRectF | None:
        selected_rect: QRectF | None = None
        normal_pen = QPen(QColor(0, 220, 255, 175), line_width)
        selected_pen = QPen(
            QColor(255, 235, 20, 255), max(line_width * 2.5, line_width + 2.0)
        )
        for label in labels:
            rectangle = self._rectangle(label)
            if rectangle is None:
                continue
            label_id = str(label.get("id", ""))
            selected = self._matches_projected_id(label_id, selected_object_id, camera_id)
            self._scene.addRect(rectangle, selected_pen if selected else normal_pen)
            if selected:
                selected_rect = rectangle
                radius = max(5.0, min(rectangle.width(), rectangle.height()) * 0.08)
                self._scene.addEllipse(
                    rectangle.center().x() - radius,
                    rectangle.center().y() - radius,
                    radius * 2,
                    radius * 2,
                    selected_pen,
                )
        return selected_rect

    def _draw_live_wireframes(
        self,
        wireframes: Iterable[ProjectedWireframe],
        selected_object_id: str | None,
        line_width: float,
    ) -> QRectF | None:
        selected_rect: QRectF | None = None
        normal_pen = QPen(QColor(40, 235, 110, 220), line_width)
        selected_pen = QPen(
            QColor(255, 235, 20, 255), max(line_width * 2.5, line_width + 2.0)
        )
        for wireframe in wireframes:
            selected = wireframe.object_id == selected_object_id
            pen = selected_pen if selected else normal_pen
            for segment in wireframe.segments:
                self._scene.addLine(
                    float(segment[0, 0]),
                    float(segment[0, 1]),
                    float(segment[1, 0]),
                    float(segment[1, 1]),
                    pen,
                )
            if selected and wireframe.bounds is not None:
                min_x, min_y, max_x, max_y = wireframe.bounds
                selected_rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
                radius = max(5.0, min(selected_rect.width(), selected_rect.height()) * 0.08)
                self._scene.addEllipse(
                    selected_rect.center().x() - radius,
                    selected_rect.center().y() - radius,
                    radius * 2,
                    radius * 2,
                    selected_pen,
                )
        return selected_rect

    @staticmethod
    def _matches_projected_id(
        label_id: str, selected_object_id: str | None, camera_id: str
    ) -> bool:
        if not selected_object_id:
            return False
        return label_id == f"{selected_object_id}_{camera_id}" or label_id.startswith(
            f"{selected_object_id}_"
        )

    @staticmethod
    def _rectangle(label: Mapping[str, Any]) -> QRectF | None:
        box = label.get("box", {})
        if not box:
            return None
        center_x = float(box["center_x"])
        center_y = float(box["center_y"])
        box_width = float(box["width"])
        box_height = float(box["length"])
        return QRectF(
            center_x - box_width / 2.0,
            center_y - box_height / 2.0,
            box_width,
            box_height,
        )

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._focus_selected and self._selected_rect is not None:
            margin_x = max(40.0, self._selected_rect.width())
            margin_y = max(40.0, self._selected_rect.height())
            focus = self._selected_rect.adjusted(-margin_x, -margin_y, margin_x, margin_y)
            self.fitInView(focus, Qt.AspectRatioMode.KeepAspectRatio)
        elif self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
