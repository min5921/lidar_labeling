"""Backward-compatible CLI entry point for packaged calibration verification."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from convert_one_chip_dataset import (
    DEFAULT_CALIBRATION_ROOT,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SOURCE_ROOT,
)
from lidar_label_tool.services import one_chip_calibration_verification as _impl


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)


def main(argv: Sequence[str] | None = None) -> int:
    _impl.DEFAULT_SOURCE_ROOT = DEFAULT_SOURCE_ROOT
    _impl.DEFAULT_CALIBRATION_ROOT = DEFAULT_CALIBRATION_ROOT
    _impl.DEFAULT_DATASET_ROOT = DEFAULT_OUTPUT_ROOT
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
