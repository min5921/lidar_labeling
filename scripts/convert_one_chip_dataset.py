"""Backward-compatible CLI entry point for the packaged conversion service."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lidar_label_tool.services import one_chip_conversion as _impl


# =============================================================================
# User-editable defaults for direct script and BAT use
# =============================================================================

DEFAULT_SOURCE_ROOT = Path(r"E:\one_chip")
DEFAULT_CALIBRATION_ROOT = (
    DEFAULT_SOURCE_ROOT / "calibration" / "results" / "apriltag_calib_main_02"
)
DEFAULT_OUTPUT_ROOT = Path(r"E:\one_chip_converted")
DEFAULT_CALIBRATION_JSON_OUTPUT = Path("artifacts/one_chip_calibration_preview.json")
DEFAULT_DATASET_ID = "one_chip_20260708"
DEFAULT_REFERENCE_FRAME = "robosense"
DEFAULT_SYNC_TOLERANCE_MS = 70.0
DEFAULT_TIMESTAMP_SOURCE = "header_aligned"
DEFAULT_CAMERA_FRAME_CONVENTION = "tool_camera"
DEFAULT_DATASET_LAYOUT = "simple"
DEFAULT_IMAGE_MODE = "block_demosaic"
DEFAULT_JPEG_QUALITY = 90
DEFAULT_PROGRESS_EVERY = 100
DEFAULT_BAGS: tuple[str, ...] = ()


def _apply_user_defaults() -> None:
    for name in (
        "DEFAULT_SOURCE_ROOT",
        "DEFAULT_CALIBRATION_ROOT",
        "DEFAULT_OUTPUT_ROOT",
        "DEFAULT_CALIBRATION_JSON_OUTPUT",
        "DEFAULT_DATASET_ID",
        "DEFAULT_REFERENCE_FRAME",
        "DEFAULT_SYNC_TOLERANCE_MS",
        "DEFAULT_TIMESTAMP_SOURCE",
        "DEFAULT_CAMERA_FRAME_CONVENTION",
        "DEFAULT_DATASET_LAYOUT",
        "DEFAULT_IMAGE_MODE",
        "DEFAULT_JPEG_QUALITY",
        "DEFAULT_PROGRESS_EVERY",
        "DEFAULT_BAGS",
    ):
        setattr(_impl, name, globals()[name])


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)


def main(argv: Sequence[str] | None = None) -> int:
    _apply_user_defaults()
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
