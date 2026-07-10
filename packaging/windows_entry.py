from __future__ import annotations

from pathlib import Path
import sys
import traceback

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.app.gui import run_gui
from lidar_label_tool.app.runtime_paths import write_crash_log


def _dataset_arg(argv: list[str]) -> Path | None:
    if len(argv) < 2:
        return None
    value = argv[1].strip().strip('"')
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


if __name__ == "__main__":
    try:
        raise SystemExit(run_gui(_dataset_arg(sys.argv), default_config_path()))
    except Exception:
        write_crash_log(traceback.format_exc())
        raise
