"""Camera/LiDAR calibration editing primitives.

This package intentionally has no Qt dependency.  The calibration editor UI lives
under :mod:`lidar_label_tool.ui.calibration_editor` and calls these validated models
and repositories.
"""

from lidar_label_tool.calibration_editor.model import (
    CalibrationDraft,
    CameraIntrinsics,
    PoseDelta,
)
from lidar_label_tool.calibration_editor.projection import (
    PointProjection,
    ProjectionStats,
    project_reference_points,
    sample_reference_points,
)
from lidar_label_tool.calibration_editor.repository import (
    CalibrationSource,
    build_calibration_document,
    default_adjusted_path,
    load_calibration_file,
    load_calibration_source,
    save_calibration_document,
)
from lidar_label_tool.calibration_editor.reference_boxes import (
    CalibrationReferenceBoxes,
)

__all__ = [
    "CalibrationDraft",
    "CalibrationReferenceBoxes",
    "CalibrationSource",
    "CameraIntrinsics",
    "PointProjection",
    "PoseDelta",
    "ProjectionStats",
    "build_calibration_document",
    "default_adjusted_path",
    "load_calibration_file",
    "load_calibration_source",
    "project_reference_points",
    "sample_reference_points",
    "save_calibration_document",
]
