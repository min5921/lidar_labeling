from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from lidar_label_tool.exporters import create_default_registry, export_frames
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import FrameSessionService


@dataclass(frozen=True, slots=True)
class LabelExportResult:
    export_format: str
    dataset_id: str
    frame_count: int
    output: Path
    exported_paths: tuple[Path, ...]


def _input_pattern_contains(target: Path, data_root: Path, pattern: str) -> bool:
    """Protect declared input folders, including absent samples, without scanning points.

    A flat ``{sample_id}.bin`` layout protects matching files at the data root,
    not every descendant: a normal ``exports/`` folder must remain usable.
    """
    source_root = data_root.resolve()
    template = pattern.replace("\\", "/")
    parent = (source_root / template).parent
    if "{sample_id}" not in str(parent):
        parent = parent.resolve()
        if parent != source_root:
            return target.is_relative_to(parent)
        if target.parent != source_root:
            return False
        relative = target.name
        expression = Path(template).name
    else:
        # Some legacy layouts place sample_id in the directory name. Matching
        # the declared directory template also protects samples not yet present.
        try:
            relative = target.relative_to(source_root).as_posix()
        except ValueError:
            return False
        expression = Path(template).parent.as_posix()
        expression = re.escape(expression).replace(
            re.escape("{sample_id}"), "([^/]+)"
        )
        matched = re.fullmatch(expression + "(?:/.*)?", relative, flags=re.IGNORECASE)
        if matched is None:
            return False
        declared_sample = source_root / template.format(sample_id=matched.group(1))
        if declared_sample.exists() or declared_sample.is_symlink():
            return True
        # A newly chosen exports/ is not automatically a sample directory just
        # because a pattern starts with {sample_id}/. Still forbid creating the
        # exact input filename that would make it discoverable as a new sample.
        expression = template
    expression = re.escape(expression.casefold()).replace(
        re.escape("{sample_id}"), "[^/]+"
    )
    return re.fullmatch(expression, relative.casefold()) is not None


def export_dataset_labels(
    dataset_root: Path,
    *,
    config: Mapping[str, Any],
    export_format: str,
    output: Path,
    frame_ids: Sequence[str] | None = None,
    workspace_root: Path | None = None,
    profile_id: str | None = None,
) -> LabelExportResult:
    """Explicitly export labels without changing source or working labels."""
    root = Path(dataset_root).resolve()
    adapter = open_dataset_adapter(root, profile_id=profile_id)
    index = adapter.scan()
    repository = open_label_repository(adapter, workspace_root=workspace_root)
    importer = WaymoLabelImporter(
        config["source_class_mappings"],
        source_format=(
            "device_centric_v2"
            if isinstance(adapter, DeviceCentricV2Adapter)
            else (
                "device_centric_json"
                if isinstance(adapter, DeviceCentricAdapter)
                else "waymo_frame_json"
            )
        ),
    )
    session = FrameSessionService(adapter, importer, repository)
    selected = tuple(frame_ids) if frame_ids else index.frame_ids
    unknown = sorted(set(selected) - set(index.frame_ids))
    if unknown:
        raise ValueError(f"unknown frame id(s): {', '.join(unknown)}")
    opened_frames = tuple(session.open_frame(frame_id) for frame_id in selected)
    labels = tuple(frame.label for frame in opened_frames)
    allowed_classes = (
        tuple(item.id for item in adapter.taxonomy.classes)
        if isinstance(adapter, DeviceCentricV2Adapter)
        else tuple(str(item["name"]) for item in config["classes"])
    )
    exporter = create_default_registry(allowed_classes).get(export_format)
    requested_output = Path(output)
    if requested_output.is_symlink() and not requested_output.is_dir():
        raise FileExistsError(f"export output is an existing symbolic link: {requested_output}")
    target = requested_output.resolve()
    # Even an empty frame's working namespace must not receive an export-format
    # JSON that would later be mistaken for a saved working label.
    roots = {root, index.root.resolve()}
    if workspace_root is not None:
        roots.add((Path(workspace_root) / index.dataset_id).resolve())
    if index.configuration_root is not None:
        roots.add(index.configuration_root.resolve())
    protected = {repository.annotation_dir.resolve()}
    for opened in opened_frames:
        source = opened.source
        source_paths = [
            *(path for paths in source.point_cloud_paths.values() for path in paths),
            *source.image_paths.values(),
            *source.source_label_paths.values(),
        ]
        for source_path in source_paths:
            resolved = source_path.resolve()
            protected.add(resolved)
            if resolved.parent != source.dataset_root.resolve():
                protected.add(resolved.parent)
    patterns: list[tuple[Path, str]] = []
    if isinstance(adapter, DeviceCentricV2Adapter):
        roots.add(adapter.data_root.resolve())
        for lidar in adapter.manifest.lidars:
            patterns.append((adapter.data_root, lidar.data_pattern))
            if lidar.timestamp is not None:
                patterns.append((adapter.data_root, lidar.timestamp.path))
        if adapter.manifest.camera is not None:
            camera = adapter.manifest.camera
            patterns.append((adapter.data_root, camera.image_pattern))
            if camera.timestamp is not None:
                patterns.append((adapter.data_root, camera.timestamp.path))
        for profile in adapter.manifest.profiles:
            if profile.camera is not None and profile.camera.calibration_path is not None:
                patterns.append((adapter.configuration_root, profile.camera.calibration_path))
    elif isinstance(adapter, DeviceCentricAdapter):
        for sensor in adapter.manifest["sensors"]:
            patterns.extend(
                (adapter.root, str(pattern)) for pattern in sensor["data_patterns"].values()
            )
        if adapter.manifest.get("calibration_path"):
            patterns.append((adapter.root, str(adapter.manifest["calibration_path"])))
        sync_path = adapter.manifest.get("synchronization", {}).get("index_path")
        if sync_path:
            patterns.append((adapter.root, str(sync_path)))
    elif isinstance(adapter, WaymoFrameCentricAdapter):
        # Every frame directory is original input, including missing labels,
        # metadata, camera and point files that future reads may discover.
        protected.update((adapter.root / frame_id).resolve() for frame_id in index.frame_ids)
    for dataset_path in roots:
        protected.update(
            (dataset_path / name).resolve()
            for name in ("annotations", "generations", "source_labels", "calibration")
        )
    single_file = len(labels) == 1 and bool(target.suffix) and not target.is_dir()
    destinations = [target]
    if not single_file:
        destinations.extend(target / f"{label.frame_id}{exporter.extension}" for label in labels)
    if any(
        destination in roots
        or any(path in protected for path in (destination, *destination.parents))
        or any(_input_pattern_contains(destination, base, pattern) for base, pattern in patterns)
        for destination in destinations
    ):
        raise ValueError(
            "export output must be separate from dataset metadata, raw input and label folders"
        )
    exported: tuple[Path, ...]
    if single_file:
        exporter.export_frame(labels[0], target)
        exported = (target,)
    else:
        if len(labels) > 1 and target.suffix and not target.is_dir():
            raise ValueError("multiple-frame output must be a directory, not a JSON path")
        if target.exists() and not target.is_dir():
            raise ValueError("multiple-frame output must be a directory")
        exported = export_frames(labels, exporter, target)
    return LabelExportResult(
        export_format=exporter.name,
        dataset_id=index.dataset_id,
        frame_count=len(exported),
        output=target,
        exported_paths=exported,
    )
