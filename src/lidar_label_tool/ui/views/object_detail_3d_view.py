from __future__ import annotations

from dataclasses import replace
import math
from typing import Iterable

import numpy as np
import pyqtgraph.opengl as gl

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.ui.colors import point_rgba
from lidar_label_tool.ui.views.pointcloud_3d_view import PointCloud3DView


class ObjectDetail3DView(PointCloud3DView):
    """Yaw-aligned local point crop centered on the selected 3D box."""

    def __init__(self) -> None:
        super().__init__()
        self.visible_point_count = 0
        self.setCameraPosition(distance=12, elevation=24, azimuth=-90)

    def set_detail(
        self,
        clouds: Iterable[PointCloudData],
        selected: LabeledObject | None,
        *,
        margin_m: float = 3.0,
        max_points: int = 120_000,
        point_size: float = 3.0,
        color_mode: str = "sensor",
        uniform_color: str = "#E8E8E8",
        box_line_width: float = 2.0,
        reset_view: bool = False,
        show_labels: bool = True,
    ) -> int:
        self._clear_items(self._point_items)
        if selected is None:
            self.set_boxes(())
            self.visible_point_count = 0
            return 0

        box = selected.box3d
        cosine = math.cos(box.yaw)
        sine = math.sin(box.yaw)
        selected_clouds: list[tuple[np.ndarray, np.ndarray]] = []
        total = 0
        for cloud in clouds:
            delta = cloud.xyz.astype(np.float64, copy=False) - np.array(
                [box.x, box.y, box.z], dtype=np.float64
            )
            local = np.column_stack(
                (
                    cosine * delta[:, 0] + sine * delta[:, 1],
                    -sine * delta[:, 0] + cosine * delta[:, 1],
                    delta[:, 2],
                )
            )
            mask = (
                (np.abs(local[:, 0]) <= box.length / 2.0 + margin_m)
                & (np.abs(local[:, 1]) <= box.width / 2.0 + margin_m)
                & (np.abs(local[:, 2]) <= box.height / 2.0 + margin_m)
            )
            positions = local[mask]
            colors = point_rgba(cloud, color_mode, uniform_color)[mask]
            selected_clouds.append((positions, colors))
            total += len(positions)

        stride = max(1, math.ceil(total / max_points)) if total else 1
        for positions, colors in selected_clouds:
            if not len(positions):
                continue
            item = gl.GLScatterPlotItem(
                pos=np.ascontiguousarray(positions[::stride], dtype=np.float32),
                color=np.ascontiguousarray(colors[::stride]),
                size=point_size,
                pxMode=True,
            )
            self.addItem(item)
            self._point_items.append(item)

        local_box = Box3D(
            x=0.0,
            y=0.0,
            z=0.0,
            length=box.length,
            width=box.width,
            height=box.height,
            yaw=0.0,
        )
        self.set_boxes(
            (replace(selected, box3d=local_box),),
            selected_id=selected.id,
            line_width=box_line_width,
            show_labels=show_labels,
        )
        distance = max(6.0, box.length * 2.5, box.width * 4.0, box.height * 4.0)
        if reset_view:
            self.setCameraPosition(distance=distance, elevation=24, azimuth=-90)
        self.visible_point_count = total
        return total
