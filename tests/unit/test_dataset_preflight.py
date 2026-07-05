from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.services.dataset_preflight import probe_writable_directory


class DatasetPreflightTests(unittest.TestCase):
    def test_probe_writable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "annotations"
            writable, error = probe_writable_directory(target)
            self.assertTrue(writable)
            self.assertIsNone(error)
            self.assertFalse(target.exists())

    def test_probe_reports_invalid_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("blocked", encoding="utf-8")
            writable, error = probe_writable_directory(blocker / "annotations")
            self.assertFalse(writable)
            self.assertIn("Error", error or "")


if __name__ == "__main__":
    unittest.main()
