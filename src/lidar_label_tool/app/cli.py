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
    inspect_parser.add_argument("--all-returns", action="store_true")
    inspect_parser.add_argument("--json", action="store_true", dest="as_json")
    gui_parser = subparsers.add_parser("gui", help="open the labeling GUI")
    gui_parser.add_argument(
        "dataset",
        type=Path,
        nargs="?",
        help="dataset root; omit it to select a folder in the GUI",
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
    preflight_parser = subparsers.add_parser(
        "preflight", help="validate dataset files and label safety without modifying data"
    )
    preflight_parser.add_argument("dataset", type=Path)
    preflight_parser.add_argument("--json", action="store_true", dest="as_json")
    preflight_parser.add_argument("--workspace", type=Path)
    stats_parser = subparsers.add_parser("stats", help="summarize source or working labels")
    stats_parser.add_argument("dataset", type=Path)
    stats_parser.add_argument("--working", action="store_true")
    stats_parser.add_argument("--json", action="store_true", dest="as_json")
    stats_parser.add_argument("--workspace", type=Path)
    return parser


def _inspect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    adapter = open_dataset_adapter(args.dataset)
    index = adapter.scan()
    frame_id = args.frame or index.frame_ids[0]
    source = adapter.load_source_frame(frame_id)
    importer = WaymoLabelImporter(config["source_class_mappings"])
    labels = importer.import_laser_labels(source)
    counts = Counter(obj.class_name for obj in labels.objects)

    point_summary: list[dict[str, object]] = []
    if args.sensor in source.point_cloud_paths:
        return_count = len(source.point_cloud_paths[args.sensor]) if args.all_returns else 1
        for number in range(1, return_count + 1):
            cloud = adapter.load_cloud_from_source(source, args.sensor, str(number))
            point_summary.append(
                {
                    "sensor": args.sensor,
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
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_preflight(report)
    return report.exit_code


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

            return run_gui(args.dataset, args.config)
        if args.command == "export":
            return _export(args)
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "stats":
            return _stats(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, ExportBatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
