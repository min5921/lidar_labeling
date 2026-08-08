from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from lidar_label_tool.ui.views.image_view import CameraImageView


class _CountingCameraImageView(CameraImageView):
    def __init__(self) -> None:
        super().__init__()
        self.load_count = 0

    def _load_pixmap(self, path: Path) -> QPixmap:
        self.load_count += 1
        return super()._load_pixmap(path)


class CameraImageViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_same_image_path_reuses_cached_pixmap_for_overlay_updates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            image = QImage(16, 12, QImage.Format.Format_RGB32)
            image.fill(QColor("black"))
            self.assertTrue(image.save(str(path)))
            view = _CountingCameraImageView()

            view.set_image(path)
            view.set_image(
                path,
                camera_labels=(
                    {"box": {"center_x": 8, "center_y": 6, "width": 4, "length": 4}},
                ),
            )

            self.assertEqual(view.load_count, 1)
            self.assertIsNotNone(view._pixmap_item)
            self.assertEqual(len(view._overlay_items), 1)

    def test_projected_points_use_requested_size_and_vivid_color(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            image = QImage(32, 32, QImage.Format.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(str(path)))
            view = CameraImageView()

            view.set_image(
                path,
                projected_points=np.array([[16.0, 16.0]], dtype=np.float32),
                projected_point_size=12.0,
            )

            self.assertEqual(len(view._overlay_items), 1)
            overlay_item = view._overlay_items[0]
            overlay = overlay_item.pixmap().toImage()  # type: ignore[attr-defined]
            center = overlay.pixelColor(16, 16)
            self.assertLess(center.red(), 50)
            self.assertGreater(center.green(), 200)
            self.assertGreater(center.blue(), 200)
            self.assertGreater(center.alpha(), 200)

    def test_camera_image_can_toggle_to_black_without_reloading_or_hiding_overlay(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            image = QImage(20, 16, QImage.Format.Format_RGB32)
            image.fill(QColor(180, 40, 20))
            self.assertTrue(image.save(str(path)))
            view = _CountingCameraImageView()
            points = np.array([[10.0, 8.0]], dtype=np.float32)

            view.set_image(
                path,
                projected_points=points,
                show_camera_image=False,
            )

            assert view._pixmap_item is not None
            hidden_pixel = view._pixmap_item.pixmap().toImage().pixelColor(0, 0)
            self.assertEqual(hidden_pixel, QColor("black"))
            self.assertEqual(len(view._overlay_items), 1)

            view.set_image(
                path,
                projected_points=points,
                show_camera_image=True,
            )

            visible_pixel = view._pixmap_item.pixmap().toImage().pixelColor(0, 0)
            self.assertEqual(visible_pixel, QColor(180, 40, 20))
            self.assertEqual(len(view._overlay_items), 1)
            self.assertEqual(view.load_count, 1)


if __name__ == "__main__":
    unittest.main()
