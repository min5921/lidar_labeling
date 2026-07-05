import unittest

from lidar_label_tool.ui.views.image_view import CameraImageView


class ImageSelectionTests(unittest.TestCase):
    def test_projected_label_id_matches_selected_lidar_object(self) -> None:
        self.assertTrue(
            CameraImageView._matches_projected_id(
                "object-id_FRONT", "object-id", "FRONT"
            )
        )
        self.assertFalse(
            CameraImageView._matches_projected_id(
                "different_FRONT", "object-id", "FRONT"
            )
        )


if __name__ == "__main__":
    unittest.main()

