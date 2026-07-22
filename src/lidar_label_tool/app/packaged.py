from __future__ import annotations

import os
from pathlib import Path
import sys


SMOKE_TEST_FLAG = "--smoke-test"


def dataset_argument(argv: list[str]) -> Path | None:
    values = [value for value in argv[1:] if value != SMOKE_TEST_FLAG]
    if not values:
        return None
    value = values[0].strip().strip('"')
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _run_smoke_test() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_OPENGL", "software")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from lidar_label_tool.app.config import default_config_path
    from lidar_label_tool.ui.workflow_dialog import WorkflowDialog

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LiDAR Label Tool")
    workflow = WorkflowDialog(default_config_path())
    workflow.show()
    QTimer.singleShot(1_500, app.quit)
    return app.exec()


def run_packaged_app(argv: list[str] | None = None) -> int:
    arguments = sys.argv if argv is None else argv
    if SMOKE_TEST_FLAG in arguments[1:]:
        return _run_smoke_test()

    from lidar_label_tool.app.config import default_config_path
    from lidar_label_tool.app.gui import run_gui

    return run_gui(dataset_argument(arguments), default_config_path())
