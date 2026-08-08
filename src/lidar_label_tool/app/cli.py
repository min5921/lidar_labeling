from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from lidar_label_tool.app.config import default_config_path, load_config
from lidar_label_tool.exporters import ExportBatchError
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.dataset_preflight import PreflightReport, validate_dataset
from lidar_label_tool.services.dataset_v2_validation import (
    DatasetV2ValidationReport,
    validate_dataset_v2,
)
from lidar_label_tool.services.dataset_resync_v2 import (
    DatasetResyncRequest,
    analyze_dataset_resync_v2,
    resynchronize_dataset_v2,
)
from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.services.label_export import export_dataset_labels
from lidar_label_tool.services.label_statistics import LabelStatistics, collect_label_statistics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lidar-label-tool")
    parser.add_argument("--config", type=Path, default=default_config_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="inspect a supported dataset")
    inspect_parser.add_argument("dataset", type=Path)
    inspect_parser.add_argument("--frame")
    inspect_parser.add_argument("--sensor", default="TOP")
    inspect_parser.add_argument("--profile")
    inspect_parser.add_argument("--all-returns", action="store_true")
    inspect_parser.add_argument("--json", action="store_true", dest="as_json")
    gui_parser = subparsers.add_parser("gui", help="open the labeling GUI")
    gui_parser.add_argument(
        "dataset",
        type=Path,
        nargs="?",
        help="dataset root; omit it to select a folder in the GUI",
    )
    gui_parser.add_argument("--profile")
    calibrate_parser = subparsers.add_parser(
        "calibrate",
        help="open the non-destructive LiDAR/camera calibration editor",
    )
    calibrate_parser.add_argument(
        "dataset",
        type=Path,
        nargs="?",
        help="dataset root; omit it to select a folder in the calibration GUI",
    )
    calibrate_parser.add_argument("--profile")
    calibrate_parser.add_argument(
        "--calibration",
        type=Path,
        help="existing generic calibration JSON to use instead of dataset auto-detection",
    )
    calibrate_parser.add_argument(
        "--output",
        type=Path,
        help="initial Save As path; the source calibration is never overwritten",
    )
    export_parser = subparsers.add_parser(
        "export", help="explicitly export labels without changing working labels"
    )
    export_parser.add_argument("dataset", type=Path)
    export_parser.add_argument("--format", required=True, dest="export_format")
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.add_argument(
        "--frame", action="append", dest="frames", help="frame id; repeat for multiple frames"
    )
    export_parser.add_argument(
        "--workspace",
        type=Path,
        help="separate workspace root used for working labels",
    )
    export_parser.add_argument("--profile")
    preflight_parser = subparsers.add_parser(
        "preflight", help="validate dataset files and label safety without modifying data"
    )
    preflight_parser.add_argument("dataset", type=Path)
    preflight_parser.add_argument("--json", action="store_true", dest="as_json")
    preflight_parser.add_argument("--workspace", type=Path)
    preflight_parser.add_argument("--profile")
    validate_v2_parser = subparsers.add_parser(
        "validate-v2",
        help="validate a generic dataset v2 configuration without modifying data",
    )
    validate_v2_parser.add_argument("dataset", type=Path)
    validate_v2_parser.add_argument("--json", action="store_true", dest="as_json")
    resync_v2_parser = subparsers.add_parser(
        "resync-v2",
        help="create and atomically activate a new generic v2 sync generation",
    )
    resync_v2_parser.add_argument("dataset", type=Path)
    resync_v2_parser.add_argument("--profile")
    resync_v2_parser.add_argument(
        "--method",
        choices=("lidar_only", "exact_stem", "timestamp_nearest"),
    )
    resync_v2_parser.add_argument("--tolerance-ms", type=float)
    resync_v2_parser.add_argument("--json", action="store_true", dest="as_json")
    stats_parser = subparsers.add_parser("stats", help="summarize source or working labels")
    stats_parser.add_argument("dataset", type=Path)
    stats_parser.add_argument("--working", action="store_true")
    stats_parser.add_argument("--json", action="store_true", dest="as_json")
    stats_parser.add_argument("--workspace", type=Path)
    stats_parser.add_argument("--profile")
    return parser


def _inspect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    adapter = open_dataset_adapter(args.dataset, profile_id=args.profile)
    index = adapter.scan()
    frame_id = args.frame or index.frame_ids[0]
    source = adapter.load_source_frame(frame_id)
    importer = WaymoLabelImporter(config["source_class_mappings"])
    labels = importer.import_laser_labels(source)
    counts = Counter(obj.class_name for obj in labels.objects)

    point_summary: list[dict[str, object]] = []
    sensor_id = args.sensor
    if sensor_id == "TOP" and sensor_id not in source.point_cloud_paths and index.lidar_ids:
        sensor_id = index.lidar_ids[0]
    if sensor_id in source.point_cloud_paths:
        return_count = len(source.point_cloud_paths[sensor_id]) if args.all_returns else 1
        for number in range(1, return_count + 1):
            cloud = adapter.load_cloud_from_source(source, sensor_id, str(number))
            point_summary.append(
                {
                    "sensor": sensor_id,
                    "return": number,
                    "points": cloud.point_count,
                    "invalid_points": cloud.invalid_point_count,
                    "attributes": sorted(cloud.attributes),
                }
            )

    summary = {
        "dataset_id": index.dataset_id,
        "adapter": index.adapter_name,
        "frames": index.frame_count,
        "lidars": list(index.lidar_ids),
        "cameras": list(index.camera_ids),
        "point_columns": list(index.point_spec.columns),
        "source_frame": index.point_spec.source_frame,
        "inspected_frame": frame_id,
        "images": sorted(source.image_paths),
        "source_label_layers": sorted(source.source_label_paths),
        "objects": len(labels.objects),
        "class_counts": dict(sorted(counts.items())),
        "point_clouds": point_summary,
    }
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}: {value}")
    return 0


def _export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = export_dataset_labels(
        args.dataset,
        config=config,
        export_format=args.export_format,
        output=args.output,
        frame_ids=args.frames,
        workspace_root=args.workspace,
        profile_id=args.profile,
    )
    print(
        json.dumps(
            {
                "format": result.export_format,
                "dataset_id": result.dataset_id,
                "frames": result.frame_count,
                "output": str(result.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _print_preflight(report: PreflightReport) -> None:
    print(f"Dataset: {report.dataset_id}")
    print(f"Adapter: {report.adapter_name}")
    print(f"Frames: {report.frame_count} (usable: {report.usable_frame_count})")
    print(f"LiDARs: {', '.join(report.lidar_ids) or 'none'}")
    print(f"Cameras: {', '.join(report.camera_ids) or 'none'}")
    print(f"Reference frame: {report.reference_frame}")
    print(
        "Working labels: "
        f"{report.working_label_count}, recovery snapshots: {report.recovery_snapshot_count}"
    )
    print(
        f"Issues: errors={report.error_count}, warnings={report.warning_count}, "
        f"info={report.info_count}"
    )
    if report.issues:
        print("\nIssues:")
        for issue in report.issues:
            context = " ".join(
                value
                for value in (issue.frame_id, issue.sensor_id, str(issue.path or ""))
                if value
            )
            suffix = f" {context}" if context else ""
            print(f"[{issue.severity}] {issue.code}{suffix} — {issue.message}")


def _preflight(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    report = validate_dataset(
        args.dataset,
        class_mapping=config["source_class_mappings"],
        workspace_root=args.workspace,
        profile_id=args.profile,
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_preflight(report)
    return report.exit_code


def _print_v2_validation(report: DatasetV2ValidationReport) -> None:
    manifest = report.manifest
    print(f"Dataset: {manifest.dataset_id if manifest is not None else 'unknown'}")
    print("Schema: 2.0 (device_centric_v2)")
    print(f"Config root: {report.config_root}")
    print(f"Data root: {report.data_root or 'unavailable'}")
    print(
        f"Profiles: {len(report.frame_indexes)}, "
        f"frames={sum(len(item.records) for item in report.frame_indexes)}"
    )
    print(
        f"Issues: errors={report.error_count}, warnings={report.warning_count}"
    )
    if report.issues:
        print("\nIssues:")
        for issue in report.issues:
            context = " ".join(
                value
                for value in (
                    issue.profile_id,
                    issue.frame_id,
                    str(issue.path or ""),
                )
                if value
            )
            suffix = f" {context}" if context else ""
            print(f"[{issue.severity}] {issue.code}{suffix} — {issue.message}")


def _validate_v2(args: argparse.Namespace) -> int:
    report = validate_dataset_v2(args.dataset)
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_v2_validation(report)
    return report.exit_code


def _resync_v2(args: argparse.Namespace) -> int:
    manifest = load_dataset_manifest_v2(args.dataset)
    profile_id = args.profile or manifest.default_profile_id
    method = args.method
    tolerance_ns = (
        round(args.tolerance_ms * 1_000_000)
        if args.tolerance_ms is not None
        else None
    )
    if tolerance_ns is not None and tolerance_ns < 0:
        raise ValueError("--tolerance-ms must be non-negative")
    request = DatasetResyncRequest(
        config_root=args.dataset,
        profile_id=profile_id,
        method=method,
        tolerance_ns=tolerance_ns,
    )
    analysis = analyze_dataset_resync_v2(request)
    result = resynchronize_dataset_v2(
        DatasetResyncRequest(
            config_root=request.config_root,
            profile_id=request.profile_id,
            method=request.method,
            tolerance_ns=request.tolerance_ns,
            expected_manifest_sha256=analysis.manifest_sha256,
            expected_source_inventory_sha256=analysis.source_inventory_sha256,
        )
    )
    payload = {
        "dataset_id": result.validation.manifest.dataset_id
        if result.validation.manifest is not None
        else None,
        "profile_id": result.profile_id,
        "manifest_revision": result.manifest_revision,
        "generation_path": str(result.generation_path),
        "sync_qa": result.qa.to_dict(),
        "camera_binding_changes": analysis.target.camera_binding_change_count,
        "frame_order_changes": analysis.target.frame_order_change_count,
        "validation": result.validation.to_dict(),
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Profile: {result.profile_id}")
        print(f"Manifest revision: {result.manifest_revision}")
        print(f"Generation: {result.generation_path}")
        print(
            f"Frames: {result.qa.lidar_frame_count}, "
            f"camera matched={result.qa.matched_camera_count}, "
            f"unmatched={result.qa.unmatched_camera_count}"
        )
    return result.validation.exit_code


def _print_statistics(statistics: LabelStatistics) -> None:
    statuses = dict(statistics.status_counts)
    print(f"Dataset: {statistics.dataset_id}")
    print(f"Mode: {statistics.mode}")
    print(f"Frames: {statistics.frame_count}")
    print(
        "Status: "
        + ", ".join(f"{name}={count}" for name, count in sorted(statuses.items()))
    )
    print(f"Visited: {statistics.visited_count}")
    print(f"Objects: {statistics.object_count}")
    print(
        "Objects/frame: "
        f"avg={statistics.average_objects_per_frame:.2f}, "
        f"min={statistics.min_objects_per_frame}, max={statistics.max_objects_per_frame}"
    )
    classes = ", ".join(
        f"{name}={count}" for name, count in statistics.class_counts
    ) or "none"
    print(f"Classes: {classes}")
    print(
        f"Labels: source={statistics.source_label_count}, "
        f"working={statistics.working_label_count}, "
        f"recovery={statistics.recovery_snapshot_count}"
    )


def _stats(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    statistics = collect_label_statistics(
        args.dataset,
        class_mapping=config["source_class_mappings"],
        working=args.working,
        workspace_root=args.workspace,
        profile_id=args.profile,
    )
    if args.as_json:
        print(json.dumps(statistics.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_statistics(statistics)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "gui":
            from lidar_label_tool.app.gui import run_gui

            return run_gui(args.dataset, args.config, profile_id=args.profile)
        if args.command == "calibrate":
            from lidar_label_tool.app.calibration_gui import run_calibration_gui

            return run_calibration_gui(
                args.dataset,
                args.config,
                profile_id=args.profile,
                calibration_path=args.calibration,
                output_path=args.output,
            )
        if args.command == "export":
            return _export(args)
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "validate-v2":
            return _validate_v2(args)
        if args.command == "resync-v2":
            return _resync_v2(args)
        if args.command == "stats":
            return _stats(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ExportBatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
