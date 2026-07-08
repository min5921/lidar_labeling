from __future__ import annotations

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.app.gui import run_gui


if __name__ == "__main__":
    raise SystemExit(run_gui(None, default_config_path()))
