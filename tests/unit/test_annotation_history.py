from dataclasses import replace
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
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

    def test_save_rebases_storage_context_but_keeps_undo_content(self) -> None:
        obj = LabeledObject(
            "obj", "car", Box3D(1, 2, 3, 4, 2, 1.5, 0),
            attributes={"vendor": {"keep": True}},
            source={"raw": {"id": "source-id"}},
            extra_fields={"custom": [1, 2]},
        )
        original = replace(
            _label(), objects=(obj,), extra_fields={"note": "before"},
            provenance={"source_fingerprints": {"source.json": "old"}},
            calibration_state={"fingerprint": "old"},
        )
        edited = replace(
            original, frame_status="in_progress", extra_fields={"note": "after"},
            objects=(replace(obj, box3d=replace(obj.box3d, x=9)),),
        )
        history = AnnotationHistory.start(original)
        history.apply(edited)
        saved = replace(
            edited, revision=1, saved_at_utc="2026-09-13T01:00:00Z",
            provenance={"source_fingerprints": {"source.json": "new"}},
            calibration_state={"fingerprint": "new"},
        )
        history.mark_saved(saved)
        undone = history.undo()
        self.assertEqual(undone.objects, original.objects)
        self.assertEqual(undone.frame_status, original.frame_status)
        self.assertEqual(undone.extra_fields, original.extra_fields)
        self.assertEqual(undone.revision, saved.revision)
        self.assertEqual(undone.saved_at_utc, saved.saved_at_utc)
        self.assertEqual(undone.provenance, saved.provenance)
        self.assertEqual(undone.calibration_state, saved.calibration_state)
        self.assertEqual(original.revision, 0)
        self.assertEqual(original.calibration_state["fingerprint"], "old")
        self.assertTrue(history.dirty)
        self.assertEqual(history.redo(), saved)
        self.assertFalse(history.dirty)

    def test_save_after_undo_rebases_redo_and_keeps_history_order(self) -> None:
        original = _label()
        history = AnnotationHistory.start(original)
        first = replace(original, frame_status="in_progress", extra_fields={"step": 1})
        second = replace(first, frame_status="reviewed", extra_fields={"step": 2})
        history.apply(first)
        history.apply(second)
        history.mark_saved(replace(second, revision=1))
        undone = history.undo()
        saved = replace(undone, revision=2, saved_at_utc="2026-09-13T02:00:00Z")
        history.mark_saved(saved)
        redone = history.redo()
        self.assertEqual(redone.revision, 2)
        self.assertEqual(redone.saved_at_utc, saved.saved_at_utc)
        self.assertEqual(redone.frame_status, "reviewed")
        self.assertEqual(redone.extra_fields, {"step": 2})
        self.assertTrue(history.dirty)
        self.assertEqual(history.undo(), saved)
        self.assertFalse(history.dirty)
        original_content = history.undo()
        self.assertEqual(original_content.frame_status, original.frame_status)
        self.assertEqual(original_content.extra_fields, original.extra_fields)
        self.assertEqual(original_content.revision, 2)


if __name__ == "__main__":
    unittest.main()
