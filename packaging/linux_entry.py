from __future__ import annotations

import sys
import traceback

from lidar_label_tool.app.packaged import run_packaged_app
from lidar_label_tool.app.runtime_paths import write_crash_log


if __name__ == "__main__":
    try:
        raise SystemExit(run_packaged_app(sys.argv))
    except Exception:
        write_crash_log(traceback.format_exc())
        raise
