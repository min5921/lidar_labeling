from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from convert_one_chip_dataset import (
    DEFAULT_CALIBRATION_ROOT,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_REFERENCE_FRAME,
    DEFAULT_SOURCE_ROOT,
    convert_calibration,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lidar_label_tool.calibration.waymo_camera import CameraCalibration  # noqa: E402
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter  # noqa: E402


# =============================================================================
# User-editable defaults
# =============================================================================
#
# These defaults follow scripts/convert_one_chip_dataset.py. Edit them here only
# if you want calibration verification to use different paths than conversion.

DEFAULT_DATASET_ROOT = DEFAULT_OUTPUT_ROOT
DEFAULT_VERIFY_FRAMES = ("000000", "002988", "002993", "003005", "003219", "003730")
DEFAULT_SAMPLE_STEP = 20
DEFAULT_REPORT_OUTPUT = Path("artifacts/calibration_verify/summary.json")
DEFAULT_OVERLAY_DIR = Path("artifacts/calibration_verify")

MAX_MATRIX_DIFF = 1e-9
MAX_ORTHOGONALITY_ERROR = 1e-6
MAX_DETERMINANT_ERROR = 1e-6


@dataclass(frozen=True, slots=True)
class VerifyIssue:
    level: str
    message: str


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _as_matrix(value: object, rows: int, cols: int, key: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.shape != (rows, cols):
        raise ValueError(f"{key} must have shape [{rows}, {cols}], got {matrix.shape}")
    return matrix


def _validate_basic_calibration(calibration: Mapping[str, Any]) -> list[VerifyIssue]:
    issues: list[VerifyIssue] = []
    if calibration.get("schema_version") != "1.0":
        issues.append(VerifyIssue("error", "schema_version must be '1.0'"))
    if calibration.get("reference_frame") != DEFAULT_REFERENCE_FRAME:
        issues.append(
            VerifyIssue(
                "warning",
                f"reference_frame is {calibration.get('reference_frame')!r}, "
                f"expected {DEFAULT_REFERENCE_FRAME!r}",
            )
        )
    lidars = calibration.get("lidars")
    if not isinstance(lidars, Mapping) or "MERGED" not in lidars:
        issues.append(VerifyIssue("error", "lidars.MERGED is missing"))
    else:
        try:
            merged = lidars["MERGED"]
            transform = _as_matrix(merged["T_reference_sensor"], 4, 4, "MERGED.T_reference_sensor")
            if not np.allclose(transform, np.eye(4), atol=MAX_MATRIX_DIFF):
                issues.append(VerifyIssue("error", "MERGED LiDAR transform is not identity"))
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(VerifyIssue("error", f"invalid MERGED LiDAR transform: {exc}"))

    cameras = calibration.get("cameras")
    if not isinstance(cameras, Mapping):
        issues.append(VerifyIssue("error", "cameras must be an object"))
        return issues
    for camera_id in ("CAM_LEFT", "CAM_RIGHT"):
        camera = cameras.get(camera_id)
        if not isinstance(camera, Mapping):
            issues.append(VerifyIssue("error", f"{camera_id} calibration is missing"))
            continue
        try:
            _as_matrix(camera["intrinsic"], 3, 3, f"{camera_id}.intrinsic")
            _as_matrix(camera["T_camera_reference"], 4, 4, f"{camera_id}.T_camera_reference")
            image_size = camera["image_size"]
            if (
                not isinstance(image_size, Sequence)
                or len(image_size) != 2
                or int(image_size[0]) <= 0
                or int(image_size[1]) <= 0
            ):
                raise ValueError("image_size must contain positive width and height")
            if camera.get("distortion_model") != "brown_conrady":
                issues.append(
                    VerifyIssue(
                        "warning",
                        f"{camera_id}.distortion_model is {camera.get('distortion_model')!r}",
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(VerifyIssue("error", f"invalid {camera_id} calibration: {exc}"))
    return issues


def _compare_to_regenerated(
    current: Mapping[str, Any],
    regenerated: Mapping[str, Any],
) -> tuple[dict[str, Any], list[VerifyIssue]]:
    issues: list[VerifyIssue] = []
    summary: dict[str, Any] = {
        "reference_frame_match": current.get("reference_frame")
        == regenerated.get("reference_frame"),
        "cameras": {},
    }
    if not summary["reference_frame_match"]:
        issues.append(VerifyIssue("error", "reference_frame differs from regenerated YAML conversion"))

    current_cameras = current.get("cameras", {})
    regenerated_cameras = regenerated.get("cameras", {})
    if not isinstance(current_cameras, Mapping) or not isinstance(regenerated_cameras, Mapping):
        return summary, [VerifyIssue("error", "camera calibration objects are invalid")]

    for camera_id in ("CAM_LEFT", "CAM_RIGHT"):
        current_camera = current_cameras[camera_id]
        regenerated_camera = regenerated_cameras[camera_id]
        intrinsic_diff = float(
            np.max(
                np.abs(
                    _as_matrix(current_camera["intrinsic"], 3, 3, f"{camera_id}.intrinsic")
                    - _as_matrix(
                        regenerated_camera["intrinsic"],
                        3,
                        3,
                        f"{camera_id}.regenerated_intrinsic",
                    )
                )
            )
        )
        transform = _as_matrix(
            current_camera["T_camera_reference"], 4, 4, f"{camera_id}.T_camera_reference"
        )
        regenerated_transform = _as_matrix(
            regenerated_camera["T_camera_reference"],
            4,
            4,
            f"{camera_id}.regenerated_T_camera_reference",
        )
        transform_diff = float(np.max(np.abs(transform - regenerated_transform)))
        rotation = transform[:3, :3]
        determinant = float(np.linalg.det(rotation))
        orthogonality_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3)))
        distortion_match = (
            current_camera.get("distortion_model")
            == regenerated_camera.get("distortion_model")
        )
        image_size_match = current_camera.get("image_size") == regenerated_camera.get("image_size")
        summary["cameras"][camera_id] = {
            "intrinsic_max_abs_diff": intrinsic_diff,
            "transform_max_abs_diff": transform_diff,
            "determinant": determinant,
            "orthogonality_error": orthogonality_error,
            "distortion_match": distortion_match,
            "image_size_match": image_size_match,
            "distortion_model": current_camera.get("distortion_model"),
            "image_size": current_camera.get("image_size"),
        }
        if intrinsic_diff > MAX_MATRIX_DIFF:
            issues.append(VerifyIssue("error", f"{camera_id} intrinsic differs from YAML conversion"))
        if transform_diff > MAX_MATRIX_DIFF:
            issues.append(VerifyIssue("error", f"{camera_id} transform differs from YAML conversion"))
        if abs(determinant - 1.0) > MAX_DETERMINANT_ERROR:
            issues.append(VerifyIssue("error", f"{camera_id} rotation determinant is not 1"))
        if orthogonality_error > MAX_ORTHOGONALITY_ERROR:
            issues.append(VerifyIssue("error", f"{camera_id} rotation is not orthogonal"))
        if not distortion_match:
            issues.append(VerifyIssue("error", f"{camera_id} distortion model differs from YAML conversion"))
        if not image_size_match:
            issues.append(VerifyIssue("error", f"{camera_id} image_size differs from YAML conversion"))
    return summary, issues


def _write_overlay(
    image_path: Path,
    output_path: Path,
    uv: np.ndarray,
    inside_mask: np.ndarray,
    *,
    max_points: int,
) -> int:
    indices = np.flatnonzero(inside_mask)
    if len(indices) == 0:
        return 0
    if len(indices) > max_points:
        picks = np.linspace(0, len(indices) - 1, max_points, dtype=np.int64)
        indices = indices[picks]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for index in indices:
        x, y = uv[index]
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 255, 64))
    image.save(output_path, quality=92)
    return int(len(indices))


def _projection_stats(
    dataset_root: Path,
    frame_ids: Sequence[str],
    *,
    sample_step: int,
    write_overlays: bool,
    overlay_dir: Path,
    overlay_max_points: int,
) -> tuple[list[dict[str, Any]], list[VerifyIssue]]:
    adapter = DeviceCentricAdapter(dataset_root)
    index = adapter.scan()
    frame_set = set(index.frame_ids)
    camera_calibrations = adapter.camera_calibrations
    if not index.lidar_ids:
        return [], [VerifyIssue("error", "dataset has no LiDAR sensors")]
    primary_lidar = index.lidar_ids[0]
    rows: list[dict[str, Any]] = []
    issues: list[VerifyIssue] = []

    for frame_id in frame_ids:
        if frame_id not in frame_set:
            issues.append(VerifyIssue("warning", f"frame {frame_id} is not in dataset"))
            continue
        source_frame = adapter.load_source_frame(frame_id)
        cloud = adapter.load_cloud_from_source(source_frame, primary_lidar)
        points = np.asarray(cloud.xyz, dtype=np.float64)
        sampled = points[::sample_step]
        frame_row: dict[str, Any] = {
            "frame_id": frame_id,
            "point_count": int(cloud.point_count),
            "sample_count": int(len(sampled)),
            "cameras": {},
        }
        for camera_id in index.camera_ids:
            calibration_data = camera_calibrations.get(camera_id)
            if not isinstance(calibration_data, Mapping):
                issues.append(VerifyIssue("error", f"{camera_id} calibration is missing in adapter"))
                continue
            camera = CameraCalibration.from_generic(camera_id, calibration_data)
            uv, valid = camera.project_vehicle_points(sampled)
            inside = (
                valid
                & (uv[:, 0] >= 0.0)
                & (uv[:, 0] < camera.width)
                & (uv[:, 1] >= 0.0)
                & (uv[:, 1] < camera.height)
            )
            valid_count = int(np.count_nonzero(valid))
            inside_count = int(np.count_nonzero(inside))
            image_path = source_frame.image_paths.get(camera_id)
            camera_row: dict[str, Any] = {
                "image": image_path.name if image_path is not None else None,
                "valid_count": valid_count,
                "inside_count": inside_count,
                "inside_sample_percent": round(100.0 * inside_count / max(1, len(sampled)), 6),
                "inside_valid_percent": round(100.0 * inside_count / max(1, valid_count), 6),
            }
            if inside_count == 0:
                issues.append(VerifyIssue("warning", f"{frame_id} {camera_id} has no in-image projected points"))
            if write_overlays and image_path is not None:
                overlay_path = overlay_dir / f"frame_{frame_id}_{camera_id}_projection.jpg"
                drawn = _write_overlay(
                    image_path,
                    overlay_path,
                    uv,
                    inside,
                    max_points=overlay_max_points,
                )
                camera_row["overlay"] = str(overlay_path)
                camera_row["overlay_points_drawn"] = drawn
            frame_row["cameras"][camera_id] = camera_row
        rows.append(frame_row)
    return rows, issues


def verify(args: argparse.Namespace) -> int:
    calibration_path = args.dataset / "calibration" / "calibration.json"
    current = _load_json(calibration_path)
    camera_frame_convention = str(
        current.get("metadata", {}).get("camera_frame_convention", "tool_camera")
    )
    regenerated = convert_calibration(
        args.calibration_root,
        reference_frame=str(current.get("reference_frame", DEFAULT_REFERENCE_FRAME)),
        camera_frame_convention=camera_frame_convention,
    )

    issues = _validate_basic_calibration(current)
    comparison, comparison_issues = _compare_to_regenerated(current, regenerated)
    issues.extend(comparison_issues)
    projections, projection_issues = _projection_stats(
        args.dataset,
        args.frames,
        sample_step=args.sample_step,
        write_overlays=args.write_overlays,
        overlay_dir=args.overlay_dir,
        overlay_max_points=args.overlay_max_points,
    )
    issues.extend(projection_issues)

    report = {
        "source_root": str(args.source),
        "dataset_root": str(args.dataset),
        "calibration_root": str(args.calibration_root),
        "calibration_path": str(calibration_path),
        "metadata": current.get("metadata", {}),
        "comparison": comparison,
        "projection_stats": projections,
        "issues": [
            {"level": issue.level, "message": issue.message}
            for issue in issues
        ],
    }
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(f"Calibration: {calibration_path}")
    print(f"Source YAML: {args.calibration_root}")
    print(f"reference_frame: {current.get('reference_frame')}")
    metadata = current.get("metadata", {})
    print(f"raw_extrinsic_convention: {metadata.get('raw_extrinsic_convention')}")
    print(f"camera_frame_convention: {metadata.get('camera_frame_convention')}")
    print("YAML comparison:")
    for camera_id, row in comparison.get("cameras", {}).items():
        print(
            f"  {camera_id}: "
            f"Kdiff={row['intrinsic_max_abs_diff']:.12g}, "
            f"Tdiff={row['transform_max_abs_diff']:.12g}, "
            f"detR={row['determinant']:.12g}, "
            f"orth_err={row['orthogonality_error']:.12g}, "
            f"distortion={row['distortion_model']}, "
            f"image_size={row['image_size']}"
        )
    print("Projection stats:")
    for frame in projections:
        print(
            f"  frame {frame['frame_id']}: "
            f"points={frame['point_count']}, sample={frame['sample_count']}"
        )
        for camera_id, row in frame["cameras"].items():
            print(
                f"    {camera_id}: image={row['image']}, "
                f"valid={row['valid_count']}, inside={row['inside_count']}, "
                f"inside_sample={row['inside_sample_percent']:.2f}%, "
                f"inside_valid={row['inside_valid_percent']:.2f}%"
            )
            if "overlay" in row:
                print(f"      overlay={row['overlay']} ({row['overlay_points_drawn']} points)")
    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]
    print(f"Issues: errors={len(errors)}, warnings={len(warnings)}")
    for issue in issues:
        print(f"[{issue.level}] {issue.message}")
    if args.report_output is not None:
        print(f"Report: {args.report_output}")
    return 1 if errors else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one_chip calibration JSON against original YAML and projection samples."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--calibration-root", type=Path, default=DEFAULT_CALIBRATION_ROOT)
    parser.add_argument(
        "--frames",
        nargs="+",
        default=list(DEFAULT_VERIFY_FRAMES),
        help="Frame IDs to use for projection checks.",
    )
    parser.add_argument("--sample-step", type=int, default=DEFAULT_SAMPLE_STEP)
    parser.add_argument(
        "--write-overlays",
        action="store_true",
        help="Write JPG overlays with projected LiDAR points.",
    )
    parser.add_argument("--overlay-dir", type=Path, default=DEFAULT_OVERLAY_DIR)
    parser.add_argument("--overlay-max-points", type=int, default=800)
    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT,
        help="JSON report output path. Use an empty string to disable.",
    )
    args = parser.parse_args(argv)
    if args.sample_step <= 0:
        parser.error("--sample-step must be positive")
    if args.overlay_max_points <= 0:
        parser.error("--overlay-max-points must be positive")
    if args.report_output == Path(""):
        args.report_output = None
    return args


if __name__ == "__main__":
    raise SystemExit(verify(parse_args()))
