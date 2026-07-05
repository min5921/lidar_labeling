from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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


if __name__ == "__main__":
    unittest.main()
