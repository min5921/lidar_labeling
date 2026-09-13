from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from lidar_label_tool.services.dataset_profiles import DatasetProfileChoice
from lidar_label_tool.ui.workflow_dialog import (
    LabelExportDialog,
    OneChipConversionDialog,
    _choose_task_profile,
)


class WorkflowDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_multiple_profiles_require_explicit_choice_or_cancel(self) -> None:
        choices = (
            DatasetProfileChoice("first", "첫 센서", "aeva"),
            DatasetProfileChoice("second", "둘째 센서", "other"),
        )
        module = "lidar_label_tool.ui.workflow_dialog"
        with patch(f"{module}._run_task", return_value=choices):
            with patch(f"{module}.QInputDialog.getItem", return_value=("", False)):
                self.assertEqual(_choose_task_profile(None, Path("dataset")), (False, None))
            with patch(
                f"{module}.QInputDialog.getItem",
                return_value=("둘째 센서 (second / LiDAR: other)", True),
            ):
                self.assertEqual(_choose_task_profile(None, Path("dataset")), (True, "second"))

    def test_export_passes_profile_and_snapshots_widgets_before_worker(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dataset.json").write_text("{}", encoding="utf-8")
            dialog = LabelExportDialog(None, Path("unused-config"))
            dialog.dataset_row.edit.setText(str(root))
            dialog.output_row.edit.setText(str(root / "export"))
            dialog.format_combo.setCurrentText("centerpoint_intermediate_json")
            module = "lidar_label_tool.ui.workflow_dialog"

            def execute_worker(_parent, _title, task):
                with patch.object(
                    dialog.format_combo, "currentText", side_effect=AssertionError("worker Qt read")
                ):
                    return task()

            with (
                patch(f"{module}._choose_task_profile", return_value=(True, "second")),
                patch(f"{module}.load_config", return_value={}),
                patch(f"{module}._run_task", side_effect=execute_worker),
                patch(f"{module}.QMessageBox.information"),
                patch(f"{module}.export_dataset_labels", return_value=SimpleNamespace(
                    frame_count=1, output=root / "export",
                )) as export,
            ):
                dialog._export()
                self.assertEqual(export.call_args.kwargs["profile_id"], "second")
                self.assertEqual(
                    export.call_args.kwargs["export_format"], "centerpoint_intermediate_json"
                )
            dialog.close()

    def test_cancelled_export_profile_does_not_start_export(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dataset.json").write_text("{}", encoding="utf-8")
            dialog = LabelExportDialog(None, Path("unused-config"))
            dialog.dataset_row.edit.setText(str(root))
            dialog.output_row.edit.setText(str(root / "export"))
            module = "lidar_label_tool.ui.workflow_dialog"
            with (
                patch(f"{module}._choose_task_profile", return_value=(False, None)),
                patch(f"{module}.load_config", return_value={}),
                patch(f"{module}.export_dataset_labels") as export,
            ):
                dialog._export()
                export.assert_not_called()
            dialog.close()

    def test_resync_does_not_require_calibration_folder(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            dataset = root / "dataset"
            source.mkdir()
            dataset.mkdir()
            (dataset / "dataset.json").write_text("{}", encoding="utf-8")
            with patch(
                "lidar_label_tool.ui.workflow_dialog.user_settings_path",
                return_value=root / "settings" / "settings.ini",
            ):
                dialog = OneChipConversionDialog(None, "resync")
            dialog.source_row.edit.setText(str(source))
            dialog.calibration_row.edit.clear()
            dialog.output_row.edit.setText(str(dataset))

            request = dialog._request()

            self.assertEqual(request.mode, "resync")
            self.assertEqual(request.output, dataset.resolve())
            dialog.close()

    def test_convert_rejects_empty_source_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibration"
            calibration.mkdir()
            with patch(
                "lidar_label_tool.ui.workflow_dialog.user_settings_path",
                return_value=root / "settings" / "settings.ini",
            ):
                dialog = OneChipConversionDialog(None, "convert")
            dialog.source_row.edit.clear()
            dialog.calibration_row.edit.setText(str(calibration))
            dialog.output_row.edit.setText(str(root / "output"))

            with self.assertRaisesRegex(ValueError, "원본 데이터 루트"):
                dialog._request()
            dialog.close()


if __name__ == "__main__":
    unittest.main()
