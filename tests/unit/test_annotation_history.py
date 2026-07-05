from dataclasses import replace
import unittest

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.services.annotation_history import AnnotationHistory


def _label(status: str = "unvisited", revision: int = 0) -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset",
        frame_id="frame_000",
        point_cloud_paths={"TOP": ("top.bin",)},
        image_paths={},
        reference_frame="vehicle",
        revision=revision,
        frame_status=status,
    )


class AnnotationHistoryTests(unittest.TestCase):
    def test_undo_redo_and_saved_baseline(self) -> None:
        original = _label()
        history = AnnotationHistory.start(original)
        edited = replace(original, frame_status="in_progress")
        self.assertTrue(history.apply(edited))
        self.assertTrue(history.dirty)
        self.assertEqual(history.undo(), original)
        self.assertFalse(history.dirty)
        self.assertEqual(history.redo(), edited)
        saved = replace(edited, revision=1)
        history.mark_saved(saved)
        self.assertFalse(history.dirty)


if __name__ == "__main__":
    unittest.main()

