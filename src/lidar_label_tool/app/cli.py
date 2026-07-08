from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from lidar_label_tool.app.config import default_config_path, load_config
from lidar_label_tool.exporters import create_default_registry, export_frames
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import FrameSessionService


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
    adapter = open_dataset_adapter(args.dataset)
    index = adapter.scan()
    repository = (
        LabelRepository.for_workspace(args.workspace, index.dataset_id)
        if args.workspace is not None
        else LabelRepository.for_sidecar(args.dataset, index.dataset_id)
    )
    importer = WaymoLabelImporter(
        config["source_class_mappings"],
        source_format=(
            "device_centric_json"
            if isinstance(adapter, DeviceCentricAdapter)
            else "waymo_frame_json"
        ),
    )
    session = FrameSessionService(adapter, importer, repository)
    frame_ids = tuple(args.frames) if args.frames else index.frame_ids
    unknown = sorted(set(frame_ids) - set(index.frame_ids))
    if unknown:
        raise ValueError(f"unknown frame id(s): {', '.join(unknown)}")
    labels = tuple(session.open_frame(frame_id).label for frame_id in frame_ids)
    exporter = create_default_registry().get(args.export_format)
    output = Path(args.output)
    exported: tuple[Path, ...]
    if len(labels) == 1 and output.suffix:
        exporter.export_frame(labels[0], output)
        exported = (output,)
    else:
        if len(labels) > 1 and output.suffix and not output.is_dir():
            raise ValueError("multiple-frame output must be a directory, not a JSON path")
        if output.exists() and not output.is_dir():
            raise ValueError("multiple-frame output must be a directory")
        exported = export_frames(labels, exporter, output)
    print(
        json.dumps(
            {
                "format": exporter.name,
                "dataset_id": index.dataset_id,
                "frames": len(exported),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
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
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
