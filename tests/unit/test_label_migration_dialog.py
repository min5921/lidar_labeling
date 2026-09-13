from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit.test_label_migration_v2 import _fixture


@pytest.fixture
def application(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_previews_then_requires_confirmation_and_commits(tmp_path: Path, application: object) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox

    from lidar_label_tool.services.background_task import TaskControl
    from lidar_label_tool.ui.label_migration_dialog import LabelMigrationV2Dialog

    request = _fixture(tmp_path)
    dialog = LabelMigrationV2Dialog(tmp_path)
    dialog.source_labels_edit.setText(str(request.source_annotation_dir))
    dialog.source_data_edit.setText(str(tmp_path))
    dialog.mapping_edit.setPlainText("Car = car")
    with patch("lidar_label_tool.ui.label_migration_dialog.run_task", side_effect=lambda parent, title, fn: fn(TaskControl())):
        dialog._analyze()
        assert dialog.plan is not None
        target = dialog.plan.target_namespace
        assert not target.exists()
        assert dialog.apply_button.isEnabled()
        assert "Frame 2개" in dialog.summary.toPlainText()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog._apply()
        assert not target.exists()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), patch.object(QMessageBox, "information"):
            dialog._apply()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.migration_result is not None
        assert dialog.migration_result.status == "migrated"
        assert target.is_dir()
    dialog.close()


def test_changed_mapping_invalidates_preview_and_cancelled_apply_requires_new_analysis(tmp_path: Path, application: object) -> None:
    from PySide6.QtWidgets import QMessageBox

    from lidar_label_tool.services.background_task import TaskControl
    from lidar_label_tool.ui.label_migration_dialog import LabelMigrationV2Dialog

    request = _fixture(tmp_path)
    dialog = LabelMigrationV2Dialog(tmp_path)
    dialog.source_labels_edit.setText(str(request.source_annotation_dir))
    dialog.source_data_edit.setText(str(tmp_path))
    dialog.mapping_edit.setPlainText("Car = car")
    with patch("lidar_label_tool.ui.label_migration_dialog.run_task", side_effect=lambda parent, title, fn: fn(TaskControl())):
        dialog._analyze()
        dialog.mapping_edit.setPlainText("Car=car\nUnknown=car")
        assert dialog.plan is None
        assert not dialog.apply_button.isEnabled()
        dialog._analyze()
        assert dialog.plan is not None
    with patch("lidar_label_tool.ui.label_migration_dialog.run_task", return_value=None), patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        dialog._apply()
    assert dialog.plan is None
    assert not dialog.apply_button.isEnabled()
    assert dialog.migration_result is None
    dialog.close()
