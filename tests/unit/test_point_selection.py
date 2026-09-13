from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.point_selection import points_in_box
from lidar_label_tool.ui.colors import SELECTED_POINT_RGBA, selected_point_colors
from lidar_label_tool.ui.views.bev_view import BevView
from lidar_label_tool.ui.views.side_view import SideView
from lidar_label_tool.ui.views.pointcloud_3d_view import PointCloud3DView
from lidar_label_tool.ui.views.object_detail_3d_view import ObjectDetail3DView


def test_point_selection_respects_yaw_height_faces_and_nonfinite_values():
    box = Box3D(10, 5, 3, 4, 2, 2, np.pi / 2)
    points = np.array(
        [[10, 5, 3], [10, 6.8, 3], [11.5, 5, 3], [10, 5, 5], [10, 5, 2], [np.nan, 5, 3]],
        dtype=np.float32,
    )
    np.testing.assert_array_equal(
        points_in_box(points, box), [True, True, False, False, True, False]
    )
    with pytest.raises(ValueError):
        points_in_box(np.zeros((4, 2)), box)


def test_highlighting_never_mutates_shared_base_colors_or_source_points():
    xyz = np.array([[0, 0, 0], [0, 0, 3], [5, 0, 0]], dtype=np.float32)
    rgba = np.tile([0.3, 0.7, 0.1, 0.8], (3, 1)).astype(np.float32)
    xyz.flags.writeable = rgba.flags.writeable = False
    before = rgba.copy()
    colors, count = selected_point_colors(xyz, rgba, Box3D(0, 0, 0, 2, 2, 2, 0))
    assert count == 1
    np.testing.assert_allclose(colors[0], SELECTED_POINT_RGBA)
    np.testing.assert_array_equal(colors[1:], rgba[1:])
    np.testing.assert_array_equal(rgba, before)
    cleared, count = selected_point_colors(xyz, rgba, None)
    assert cleared is rgba and count == 0


@pytest.mark.parametrize("view_class", [PointCloud3DView, BevView, SideView])
def test_view_selection_moves_and_clears_without_reloading_points(view_class):
    app = QApplication.instance() or QApplication([])
    view = view_class()
    xyz = np.array([[0, 0, 0], [0, 0, 3], [5, 0, 0]], dtype=np.float32)
    cloud = PointCloudData(xyz, {}, "aeva", "1", "lidar:aeva", Path("test.bin"))
    view.set_clouds((cloud,))
    item_ids = [id(item) for item in view._point_items]
    base = [data.rgba.copy() for data in view._render_clouds]
    box = Box3D(0, 0, 0, 2, 2, 2, 0)
    view.set_selected_box(box)
    assert view.selected_point_count == 1
    view.set_selected_box(replace(box, x=5))
    assert view.selected_point_count == 1
    view.set_selected_box(None)
    assert view.selected_point_count == 0
    assert [id(item) for item in view._point_items] == item_ids
    for original, data in zip(base, view._render_clouds):
        np.testing.assert_array_equal(data.rgba, original)
    view.close()
    app.processEvents()


def test_detail_view_highlights_only_points_inside_box_not_surrounding_crop():
    app = QApplication.instance() or QApplication([])
    view = ObjectDetail3DView()
    cloud = PointCloudData(
        np.array([[0, 0, 3], [0, 0, 4.5]], dtype=np.float32),
        {},
        "aeva",
        "1",
        "lidar:aeva",
        Path("test.bin"),
    )
    obj = LabeledObject("sign", "sign", Box3D(0, 0, 3, 2, 1, 1, 0))
    view.set_detail((cloud,), obj)
    assert view.selected_point_count == 1
    assert view.visible_point_count == 2
    view.set_detail((cloud,), obj, highlight_selected=False)
    assert view.selected_point_count == 0
    view.set_detail((cloud,), None)
    assert view.selected_point_count == 0 and view.visible_point_count == 0
    view.close()
    app.processEvents()
