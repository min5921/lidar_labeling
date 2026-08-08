from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Mapping
from uuid import uuid4

import numpy as np

from lidar_label_tool import __version__
from lidar_label_tool.calibration_editor.model import CalibrationDraft
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.dataset import DatasetAdapter, DatasetIndex
from lidar_label_tool.io.json_schema import read_json_document, validate_json_document
from lidar_label_tool.io.labels.waymo_importer import sha256_file


_SAFE_FILE_PART = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class CalibrationSource:
    """Existing generic or embedded calibration available for editing."""

    document: Mapping[str, Any] | None
    generic_cameras: Mapping[str, Mapping[str, Any]]
    waymo_cameras: Mapping[str, Mapping[str, Any]]
    source_path: Path | None
    source_fingerprint: str | None
    source_kind: str

    def draft_for(
        self,
        camera_id: str,
        reference_frame: str,
        image_size: tuple[int, int],
    ) -> CalibrationDraft:
        generic = self.generic_cameras.get(camera_id)
        if generic is not None:
            return CalibrationDraft.from_generic(
                camera_id,
                reference_frame,
                generic,
                source_path=self.source_path,
                source_fingerprint=self.source_fingerprint,
            )
        waymo = self.waymo_cameras.get(camera_id)
        if waymo is not None:
            if self.source_path is None or self.source_fingerprint is None:
                raise ValueError("Waymo calibration source provenance is missing")
            return CalibrationDraft.from_waymo(
                camera_id,
                reference_frame,
                waymo,
                source_path=self.source_path,
                source_fingerprint=self.source_fingerprint,
            )
        return CalibrationDraft.new(camera_id, reference_frame, image_size)


def load_calibration_source(
    adapter: DatasetAdapter,
    index: DatasetIndex,
) -> CalibrationSource:
    """Load calibration provenance without changing any dataset file."""
    source_path: Path | None = None
    source_kind = "new"
    if isinstance(adapter, DeviceCentricV2Adapter):
        camera = adapter.profile.camera
        if camera is not None and camera.calibration_path is not None:
            source_path = _safe_relative_path(
                adapter.configuration_root,
                camera.calibration_path,
            )
            source_kind = "generic"
    elif isinstance(adapter, DeviceCentricAdapter):
        relative = adapter.manifest.get("calibration_path")
        if relative:
            source_path = _safe_relative_path(index.root, str(relative))
            source_kind = "generic"
    elif isinstance(adapter, WaymoFrameCentricAdapter):
        source_path = index.root / "segment.json"
        fingerprint = sha256_file(source_path)
        cameras = {
            str(item["name"]): dict(item)
            for item in adapter.segment.get("camera_calibrations", ())
            if isinstance(item, Mapping) and "name" in item
        }
        return CalibrationSource(
            document=None,
            generic_cameras={},
            waymo_cameras=cameras,
            source_path=source_path,
            source_fingerprint=fingerprint,
            source_kind="waymo_embedded",
        )

    if source_path is None:
        return CalibrationSource(None, {}, {}, None, None, source_kind)
    source = load_calibration_file(source_path)
    if isinstance(adapter, DeviceCentricV2Adapter):
        camera = adapter.profile.camera
        expected = camera.calibration_sha256 if camera is not None else None
        if expected is not None and source.source_fingerprint != expected:
            raise ValueError(
                "calibration fingerprint does not match the active v2 profile"
            )
    if source.document is not None:
        source_reference = str(source.document.get("reference_frame", ""))
        if source_reference != index.reference_frame:
            raise ValueError(
                "calibration reference_frame does not match the active dataset: "
                f"{source_reference!r} != {index.reference_frame!r}"
            )
    return source


def load_calibration_file(source_path: Path) -> CalibrationSource:
    """Load and validate an explicitly selected generic calibration JSON."""
    path = Path(source_path).resolve()
    if not path.is_file():
        raise ValueError(f"calibration source file does not exist: {path}")
    loaded = read_json_document(path)
    if not isinstance(loaded, Mapping):
        raise ValueError(f"calibration root must be an object: {path}")
    validate_json_document(loaded, "calibration.schema.json")
    raw_cameras = loaded.get("cameras", {})
    cameras = (
        {
            str(camera_id): dict(value)
            for camera_id, value in raw_cameras.items()
            if isinstance(value, Mapping)
        }
        if isinstance(raw_cameras, Mapping)
        else {}
    )
    return CalibrationSource(
        document=dict(loaded),
        generic_cameras=cameras,
        waymo_cameras={},
        source_path=path,
        source_fingerprint=sha256_file(path),
        source_kind="generic",
    )


def build_calibration_document(
    source: CalibrationSource,
    draft: CalibrationDraft,
    adapter: DatasetAdapter,
    index: DatasetIndex,
    *,
    verified_frame_ids: tuple[str, ...] = (),
    projection_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and schema-check a non-destructive generic calibration document."""
    existing = source.document if isinstance(source.document, Mapping) else {}
    raw_lidars = existing.get("lidars", {})
    lidars: dict[str, Any] = (
        deepcopy(dict(raw_lidars)) if isinstance(raw_lidars, Mapping) else {}
    )
    identity = np.eye(4, dtype=np.float64).tolist()
    for lidar_id in index.lidar_ids:
        if lidar_id in lidars:
            continue
        spec = adapter.point_spec_for(lidar_id)
        if spec.source_frame == index.reference_frame:
            lidars[lidar_id] = {"T_reference_sensor": identity}
    if not lidars:
        raise ValueError(
            "cannot save camera calibration without a reference-frame LiDAR entry"
        )

    raw_cameras = existing.get("cameras", {})
    cameras: dict[str, Any] = (
        deepcopy(dict(raw_cameras)) if isinstance(raw_cameras, Mapping) else {}
    )
    cameras[draft.camera_id] = draft.camera_entry()

    raw_metadata = existing.get("metadata", {})
    metadata: dict[str, Any] = (
        deepcopy(dict(raw_metadata)) if isinstance(raw_metadata, Mapping) else {}
    )
    editor_metadata: dict[str, Any] = {
        "tool": "lidar-label-tool",
        "tool_version": __version__,
        "saved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_id": index.dataset_id,
        "profile_id": index.profile_id,
        "camera_id": draft.camera_id,
        "base_source_kind": draft.source_kind,
        "base_source_path": str(draft.source_path) if draft.source_path else None,
        "base_source_sha256": draft.source_fingerprint,
        "verified_frame_ids": list(dict.fromkeys(verified_frame_ids)),
        "effective_T_camera_reference": draft.effective_transform.tolist(),
        "correction_semantics": "T_effective = correction_delta @ T_camera_reference",
    }
    if projection_summary is not None:
        editor_metadata["last_projection"] = dict(projection_summary)
    metadata["calibration_editor"] = editor_metadata

    document = {
        "schema_version": "1.0",
        "reference_frame": index.reference_frame,
        "lidars": lidars,
        "cameras": cameras,
        "metadata": metadata,
    }
    validate_json_document(document, "calibration.schema.json")
    return document


def save_calibration_document(
    target: Path,
    document: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    expected_source_fingerprint: str | None = None,
) -> str:
    """Atomically save JSON and return its SHA-256 fingerprint.

    The original source calibration is an explicit forbidden target. Existing
    adjusted outputs receive one recoverable ``.bak`` copy.
    """
    output = Path(target).resolve()
    if output.suffix.lower() != ".json":
        raise ValueError("calibration output must use the .json extension")
    if source_path is not None and output == Path(source_path).resolve():
        raise ValueError("the source calibration cannot be overwritten; use Save As")
    if source_path is not None and expected_source_fingerprint is not None:
        source = Path(source_path).resolve()
        if not source.is_file() or sha256_file(source) != expected_source_fingerprint:
            raise RuntimeError(
                "the source calibration changed after it was loaded; reload before saving"
            )
    validate_json_document(document, "calibration.schema.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    initial_exists = output.is_file()
    initial_fingerprint = sha256_file(output) if initial_exists else None
    token = uuid4().hex
    temporary = output.with_name(f".{output.name}.{token}.tmp")
    backup_temporary = output.with_name(f".{output.name}.{token}.bak.tmp")
    backup = output.with_suffix(output.suffix + ".bak")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        reloaded = read_json_document(temporary)
        validate_json_document(reloaded, "calibration.schema.json")

        if initial_exists:
            if not output.is_file() or sha256_file(output) != initial_fingerprint:
                raise RuntimeError("calibration output changed during save")
            shutil.copy2(output, backup_temporary)
            os.replace(backup_temporary, backup)
        elif output.exists():
            raise RuntimeError("calibration output appeared during save")
        os.replace(temporary, output)
    finally:
        for path in (temporary, backup_temporary):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return sha256_file(output)


def default_adjusted_path(index: DatasetIndex, camera_id: str) -> Path:
    root = index.configuration_root or index.root
    safe_camera = _SAFE_FILE_PART.sub("_", camera_id).strip("._") or "camera"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / "calibration" / "adjusted" / f"{safe_camera}.adjusted.{stamp}.json"


def _safe_relative_path(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError(f"unsafe calibration path: {value}")
    base = Path(root).resolve()
    candidate = base.joinpath(*pure.parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"calibration path escapes configuration root: {value}") from exc
    return candidate
