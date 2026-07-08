from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from lidar_label_tool.app.gui import _confirm_dataset_open
from lidar_label_tool.services.dataset_preflight import (
    PreflightIssue,
    inspect_dataset,
    validate_dataset,
)
from tests.fixture_builders import CLASS_MAPPING, create_device_dataset


class GuiPreflightTests(unittest.TestCase):
    def test_usable_dataset_with_errors_can_be_opened_explicitly(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            quick = inspect_dataset(root, probe_write=False)
            report = validate_dataset(root, class_mapping=CLASS_MAPPING)
            report = replace(
                report,
                issues=(PreflightIssue("error", "test_error", "검증 오류"),),
            )
            with patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as question:
                accepted = _confirm_dataset_open(quick, report, always_confirm=False)

            self.assertTrue(accepted)
            question.assert_called_once()

    def test_dataset_without_usable_lidar_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            quick = inspect_dataset(root, probe_write=False)
            report = validate_dataset(root, class_mapping=CLASS_MAPPING)
            report = replace(
                report,
                usable_frame_count=0,
                issues=(PreflightIssue("error", "no_lidar", "사용 가능한 LiDAR 없음"),),
            )
            with patch.object(QMessageBox, "critical") as critical:
                accepted = _confirm_dataset_open(quick, report, always_confirm=False)

            self.assertFalse(accepted)
            critical.assert_called_once()


if __name__ == "__main__":
    unittest.main()
