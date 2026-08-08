from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.ui.calibration_editor.window import CalibrationEditorWindow
from lidar_label_tool.workers.frame_loader import load_frame_payload
from tests.fixture_builders import create_v2_dataset


class CalibrationEditorWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_view_ratio_and_temporary_reference_box_flow(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 calibration GUI"
            root.mkdir()
            create_v2_dataset(root, frame_count=1, with_camera=True)

            with patch.object(CalibrationEditorWindow, "_request_frame"):
                window = CalibrationEditorWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            window._set_view_ratio(72)
            self.assertEqual(window.view_ratio_label.text(), "72 : 28")
            self.assertIsNotNone(window.bev_view)
            self.assertEqual(window.point_size.value(), 4.0)
            self.assertEqual(window.point_size.maximum(), 30.0)
            self.assertFalse(window.point_outline.isChecked())
            self.assertTrue(window.show_camera_image.isChecked())
            with patch.object(window, "_schedule_preview") as schedule_preview:
                window.point_size_slider.setValue(18)
                self.assertEqual(window.point_size.value(), 18.0)
                window.point_size.setValue(9.0)
                self.assertEqual(window.point_size_slider.value(), 9)
            self.assertEqual(schedule_preview.call_count, 2)

            payload = load_frame_payload(
                window.adapter,
                window.importer,
                "000000",
                window.repository,
            )
            window.request_generation = 1
            with (
                patch.object(window.point_view, "set_clouds", return_value=1) as point_clouds,
                patch.object(window.bev_view, "set_clouds", return_value=1) as bev_clouds,
                patch.object(window.point_view, "set_boxes"),
                patch.object(window.bev_view, "set_boxes"),
                patch.object(
                    window.image_view, "set_image", return_value=True
                ) as set_image,
            ):
                window._accept_frame(1, payload)

            point_clouds.assert_called_once()
            bev_clouds.assert_called_once()
            self.assertFalse(set_image.call_args.kwargs["projected_point_outline"])
            self.assertTrue(set_image.call_args.kwargs["show_camera_image"])
            draft = window.drafts.get("head_camera")
            self.assertIsNotNone(draft)
            source_objects_before = payload.label.objects

            window.show_camera_image.setChecked(False)
            with patch.object(window.image_view, "set_image", return_value=True) as hidden:
                window._render_preview()
            self.assertFalse(hidden.call_args.kwargs["show_camera_image"])

            with (
                patch.object(window, "_render_lidar_boxes"),
                patch.object(window, "_schedule_preview"),
            ):
                window._create_reference_box(
                    8.0,
                    1.0,
                    length=3.5,
                    width=1.5,
                )

            reference_boxes = window.reference_boxes.for_frame("000000")
            self.assertEqual(len(reference_boxes), 1)
            self.assertEqual(payload.label.objects, source_objects_before)
            assert draft is not None
            wireframes = window._project_boxes(draft.effective_camera_calibration())
            self.assertEqual([wireframe.object_id for wireframe in wireframes], [reference_boxes[0].id])
            window.close()


if __name__ == "__main__":
    unittest.main()
