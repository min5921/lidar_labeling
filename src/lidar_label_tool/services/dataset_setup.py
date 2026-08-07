from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Callable, Mapping
from uuid import uuid4

from lidar_label_tool.domain.dataset_v2 import DatasetManifestV2, SyncMethod
from lidar_label_tool.domain.point_cloud import PointCloudSpec
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader
from lidar_label_tool.io.loaders.pcd_loader import PcdPointCloudLoader
from lidar_label_tool.io.dataset_v2 import (
    canonical_frame_index_bytes,
    parse_dataset_manifest_v2,
)
from lidar_label_tool.io.json_schema import validate_json_document
from lidar_label_tool.services.dataset_discovery import SensorCandidate
from lidar_label_tool.services.dataset_v2_validation import (
    DatasetV2ValidationReport,
    validate_dataset_manifest_v2,
    validate_dataset_v2,
)
from lidar_label_tool.services.timestamp_synchronizer import (
    SynchronizationQa,
    SynchronizationResult,
    make_sensor_samples,
    synchronize_profile,
)
from lidar_label_tool.services.timestamp_table import (
    TimestampTable,
    TimestampUnit,
    read_timestamp_table,
)


ProgressCallback = Callable[[str, int, int, str], None]
CancelCheck = Callable[[], bool]
_MACHINE_ID = re.compile(
    r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))"
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$"
)


class DatasetSetupError(ValueError):
    pass


class DatasetSetupConflictError(DatasetSetupError):
    pass


class DatasetSetupCancelled(DatasetSetupError):
    pass


@dataclass(frozen=True, slots=True)
class TimestampSetup:
    relative_path: str
    sample_id_column: str
    value_column: str
    unit: TimestampUnit
    clock_domain: str
    offset_ns: int = 0


@dataclass(frozen=True, slots=True)
class LidarSetup:
    candidate: SensorCandidate
    sensor_id: str
    display_name: str
    coordinate_frame: str
    point_columns: tuple[str, ...]
    profile_id: str
    profile_display_name: str
    sync_method: SyncMethod
    tolerance_ns: int | None = None
    timestamp: TimestampSetup | None = None
    point_dtype: str = "float32"
    byte_order: str = "little-endian"


@dataclass(frozen=True, slots=True)
class CameraSetup:
    candidate: SensorCandidate
    sensor_id: str
    display_name: str
    coordinate_frame: str
    timestamp: TimestampSetup | None = None
    mode: str = "display_only"
    calibration_path: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetSetupRequest:
    source_root: Path
    config_root: Path
    display_name: str
    lidars: tuple[LidarSetup, ...]
    taxonomy: Mapping[str, Any]
    coordinate_system_confirmed: bool
    camera: CameraSetup | None = None
    dataset_id: str | None = None
    default_profile_id: str | None = None
    expected_manifest_sha256: str | None = None
    expected_source_inventory_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetSetupAnalysis:
    source_root: Path
    config_root: Path
    dataset_id: str
    source_inventory_sha256: str
    sync_qa: tuple[tuple[str, SynchronizationQa], ...]
    source_file_count: int


@dataclass(frozen=True, slots=True)
class DatasetSetupResult:
    config_root: Path
    data_root: Path
    manifest: DatasetManifestV2
    generation_path: Path
    validation: DatasetV2ValidationReport
    sync_qa: tuple[tuple[str, SynchronizationQa], ...]
    source_inventory_sha256: str


def analyze_generic_dataset(
    request: DatasetSetupRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetSetupAnalysis:
    """Validate and synchronize inputs without creating configuration files."""
    source_root = Path(request.source_root).resolve()
    config_root = Path(request.config_root).resolve()
    _validate_request(request, source_root, config_root)
    _require_initial_configuration_available(request, config_root)
    _validate_point_candidates(request, source_root)
    _check_cancel(cancel_check)
    selected_source_paths = _selected_source_paths(request, source_root, config_root)
    source_hashes = _hash_paths(
        selected_source_paths,
        phase="source_fingerprint",
        progress=progress,
        cancel_check=cancel_check,
    )
    source_inventory_sha256 = _inventory_hash(source_root, source_hashes)
    timestamp_tables = _load_timestamp_tables(request, source_root)
    sync_results = _synchronize_request(
        request,
        timestamp_tables,
        progress=progress,
        cancel_check=cancel_check,
    )
    return DatasetSetupAnalysis(
        source_root=source_root,
        config_root=config_root,
        dataset_id=request.dataset_id or new_dataset_id(),
        source_inventory_sha256=source_inventory_sha256,
        sync_qa=tuple(
            (lidar.profile_id, sync_results[lidar.profile_id].qa)
            for lidar in request.lidars
        ),
        source_file_count=len(selected_source_paths),
    )


def create_generic_dataset(
    request: DatasetSetupRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetSetupResult:
    """Create a complete v2 configuration and commit dataset.json last."""
    source_root = Path(request.source_root).resolve()
    config_root = Path(request.config_root).resolve()
    _validate_request(request, source_root, config_root)
    _require_initial_configuration_available(request, config_root)
    _validate_point_candidates(request, source_root)
    _check_cancel(cancel_check)

    config_root.mkdir(parents=True, exist_ok=True)
    manifest_path = config_root / "dataset.json"

    selected_source_paths = _selected_source_paths(request, source_root, config_root)
    before_hashes = _hash_paths(
        selected_source_paths,
        phase="source_fingerprint",
        progress=progress,
        cancel_check=cancel_check,
    )
    source_inventory_sha256 = _inventory_hash(source_root, before_hashes)
    if (
        request.expected_source_inventory_sha256 is not None
        and request.expected_source_inventory_sha256 != source_inventory_sha256
    ):
        raise DatasetSetupConflictError(
            "source files changed after setup analysis; analyze again before creating"
        )
    timestamp_tables = _load_timestamp_tables(request, source_root)
    sync_results = _synchronize_request(
        request,
        timestamp_tables,
        progress=progress,
        cancel_check=cancel_check,
    )

    token = uuid4().hex
    generation_name = "generation-000001"
    generations_root = config_root / "generations"
    generation_path = generations_root / generation_name
    staging_path = generations_root / f".{generation_name}.{token}.tmp"
    manifest_temporary = config_root / f".dataset.json.{token}.tmp"
    generation_activated = False
    manifest_committed = False
    committed_manifest_bytes: bytes | None = None
    try:
        if generation_path.exists():
            raise DatasetSetupConflictError(
                f"generation path already exists: {generation_path}"
            )
        (staging_path / "sync").mkdir(parents=True, exist_ok=False)
        taxonomy_path = staging_path / "taxonomy.json"
        _write_json_fsynced(taxonomy_path, dict(request.taxonomy))
        validate_json_document(request.taxonomy, "taxonomy.schema.json")
        taxonomy_sha256 = _sha256(taxonomy_path)

        index_metadata: dict[str, tuple[str, str, int]] = {}
        for position, lidar in enumerate(request.lidars, start=1):
            result = sync_results[lidar.profile_id]
            payload = canonical_frame_index_bytes(result.records)
            target = staging_path / "sync" / f"{lidar.profile_id}.frames.jsonl"
            _write_bytes_fsynced(target, payload)
            index_metadata[lidar.profile_id] = (
                f"generations/{generation_name}/sync/{lidar.profile_id}.frames.jsonl",
                hashlib.sha256(payload).hexdigest(),
                len(result.records),
            )
            if progress is not None:
                progress("write_generation", position, len(request.lidars), target.name)

        os.replace(staging_path, generation_path)
        generation_activated = True
        document = _manifest_document(
            request,
            source_root=source_root,
            config_root=config_root,
            timestamp_tables=timestamp_tables,
            index_metadata=index_metadata,
            taxonomy_sha256=taxonomy_sha256,
            source_inventory_sha256=source_inventory_sha256,
            generation_name=generation_name,
        )
        manifest = parse_dataset_manifest_v2(document)
        candidate_report = validate_dataset_manifest_v2(config_root, manifest)
        candidate_report.require_valid()

        after_hashes = _hash_paths(
            selected_source_paths,
            phase="verify_source_unchanged",
            progress=progress,
            cancel_check=cancel_check,
        )
        if before_hashes != after_hashes:
            raise DatasetSetupConflictError(
                "source point/image/timestamp/calibration files changed during setup"
            )
        if manifest_path.exists():
            raise DatasetSetupConflictError(
                "dataset.json was created by another process during setup"
            )
        _write_json_fsynced(manifest_temporary, document)
        parse_dataset_manifest_v2(json.loads(manifest_temporary.read_text(encoding="utf-8")))
        committed_manifest_bytes = manifest_temporary.read_bytes()
        _check_cancel(cancel_check)
        os.replace(manifest_temporary, manifest_path)
        manifest_committed = True
        final_report = validate_dataset_v2(config_root)
        final_report.require_valid()
        return DatasetSetupResult(
            config_root=config_root,
            data_root=source_root,
            manifest=manifest,
            generation_path=generation_path,
            validation=final_report,
            sync_qa=tuple(
                (lidar.profile_id, sync_results[lidar.profile_id].qa)
                for lidar in request.lidars
            ),
            source_inventory_sha256=source_inventory_sha256,
        )
    except Exception:
        if manifest_committed and committed_manifest_bytes is not None:
            manifest_committed = not _remove_owned_manifest(
                manifest_path,
                committed_manifest_bytes,
            )
        if not manifest_committed and generation_activated:
            _remove_owned_generation(generation_path, generations_root, generation_name)
        raise
    finally:
        for path in (manifest_temporary, staging_path):
            _remove_owned_temporary(path, config_root)


def taxonomy_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    classes = config.get("classes")
    if not isinstance(classes, list) or not classes:
        raise DatasetSetupError("config classes must be a non-empty list")
    used: set[str] = set()
    class_ids_by_name: dict[str, str] = {}
    taxonomy_classes: list[dict[str, Any]] = []
    for item in classes:
        if not isinstance(item, Mapping):
            raise DatasetSetupError("each config class must be an object")
        display_name = str(item["name"])
        class_id = _machine_id_from_display(display_name, "class", used)
        used.add(class_id)
        class_ids_by_name[display_name] = class_id
        size = item["default_size"]
        class_data: dict[str, Any] = {
            "id": class_id,
            "display_name": display_name,
            "color": str(item["color"]),
            "default_size_m": {
                "length": float(size[0]),
                "width": float(size[1]),
                "height": float(size[2]),
            },
        }
        if item.get("shortcut"):
            class_data["shortcut"] = str(item["shortcut"])
        taxonomy_classes.append(class_data)
    raw_mappings = config.get("source_class_mappings", {})
    source_mapping = {
        str(source): class_ids_by_name[str(target)]
        for source, target in raw_mappings.items()
        if str(target) in class_ids_by_name
    }
    result: dict[str, Any] = {
        "schema_version": "2.0",
        "display_name": "LiDAR Label Tool 기본 클래스",
        "classes": taxonomy_classes,
        "source_mappings": {"legacy": source_mapping},
    }
    unknown = class_ids_by_name.get("Unknown")
    if unknown is not None:
        result["fallback_class_id"] = unknown
    validate_json_document(result, "taxonomy.schema.json")
    return result


def new_dataset_id() -> str:
    return f"ds_{uuid4().hex}"


def _validate_request(
    request: DatasetSetupRequest,
    source_root: Path,
    config_root: Path,
) -> None:
    if not source_root.is_dir():
        raise DatasetSetupError(f"source root is not a directory: {source_root}")
    if not request.display_name.strip():
        raise DatasetSetupError("display_name is required")
    if not request.coordinate_system_confirmed:
        raise DatasetSetupError(
            "coordinate system must be explicitly confirmed as meter/forward/left/up"
        )
    if not request.lidars:
        raise DatasetSetupError("at least one LiDAR candidate must be selected")
    ids: list[str] = []
    profile_ids: list[str] = []
    for lidar in request.lidars:
        if lidar.candidate.kind != "lidar" or not lidar.candidate.samples:
            raise DatasetSetupError(f"invalid LiDAR candidate: {lidar.display_name}")
        _require_machine_id(lidar.sensor_id, "lidar sensor_id")
        _require_machine_id(lidar.profile_id, "profile_id")
        ids.append(lidar.sensor_id)
        profile_ids.append(lidar.profile_id)
        if len(set(lidar.point_columns)) != len(lidar.point_columns):
            raise DatasetSetupError(f"duplicate point columns: {lidar.sensor_id}")
        if not {"x", "y", "z"}.issubset(lidar.point_columns):
            raise DatasetSetupError(f"point columns require x/y/z: {lidar.sensor_id}")
        if lidar.sync_method == "lidar_only" and request.camera is not None:
            continue
        if lidar.sync_method != "lidar_only" and request.camera is None:
            raise DatasetSetupError(
                f"profile {lidar.profile_id} selects camera sync without a camera"
            )
        if lidar.sync_method == "timestamp_nearest" and lidar.timestamp is None:
            raise DatasetSetupError(
                f"profile {lidar.profile_id} requires a LiDAR timestamp table"
            )
    if len(ids) != len(set(ids)) or len(profile_ids) != len(set(profile_ids)):
        raise DatasetSetupError("sensor IDs and profile IDs must be unique")
    if request.camera is not None:
        if request.camera.candidate.kind != "camera" or not request.camera.candidate.samples:
            raise DatasetSetupError("invalid camera candidate")
        _require_machine_id(request.camera.sensor_id, "camera sensor_id")
        if request.camera.sensor_id in ids:
            raise DatasetSetupError("camera and LiDAR sensor IDs must be unique")
        if any(lidar.sync_method == "timestamp_nearest" for lidar in request.lidars):
            if request.camera.timestamp is None:
                raise DatasetSetupError(
                    "timestamp_nearest requires a camera timestamp table"
                )
    default_profile = request.default_profile_id or request.lidars[0].profile_id
    if default_profile not in profile_ids:
        raise DatasetSetupError("default_profile_id does not exist")
    if request.dataset_id is not None:
        _require_machine_id(request.dataset_id, "dataset_id")
    validate_json_document(request.taxonomy, "taxonomy.schema.json")
    if config_root.exists() and not config_root.is_dir():
        raise DatasetSetupError(f"config root is not a directory: {config_root}")


def _require_initial_configuration_available(
    request: DatasetSetupRequest,
    config_root: Path,
) -> None:
    manifest_path = config_root / "dataset.json"
    if not manifest_path.exists():
        return
    actual = _sha256(manifest_path)
    if request.expected_manifest_sha256 is None:
        raise DatasetSetupConflictError(
            "dataset.json already exists; use the explicit reconfiguration workflow"
        )
    if actual != request.expected_manifest_sha256:
        raise DatasetSetupConflictError(
            "dataset.json changed after setup analysis; rescan before applying"
        )
    raise DatasetSetupConflictError(
        "editing an existing v2 manifest is not part of initial dataset creation"
    )


def _synchronize_request(
    request: DatasetSetupRequest,
    timestamp_tables: Mapping[tuple[str, str], TimestampTable],
    *,
    progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> dict[str, SynchronizationResult]:
    camera_samples = (
        make_sensor_samples(
            request.camera.sensor_id,
            (
                (sample.source_sample_id, sample.relative_path)
                for sample in request.camera.candidate.samples
            ),
        )
        if request.camera is not None
        else ()
    )
    camera_timestamp = (
        timestamp_tables.get(("camera", request.camera.sensor_id))
        if request.camera is not None
        else None
    )
    results: dict[str, SynchronizationResult] = {}
    for position, lidar in enumerate(request.lidars, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress("synchronize", position, len(request.lidars), lidar.display_name)
        lidar_samples = make_sensor_samples(
            lidar.sensor_id,
            (
                (sample.source_sample_id, sample.relative_path)
                for sample in lidar.candidate.samples
            ),
        )
        results[lidar.profile_id] = synchronize_profile(
            profile_id=lidar.profile_id,
            lidar_samples=lidar_samples,
            method=lidar.sync_method,
            camera_samples=camera_samples if lidar.sync_method != "lidar_only" else (),
            lidar_timestamps=timestamp_tables.get(("lidar", lidar.sensor_id)),
            camera_timestamps=(
                camera_timestamp if lidar.sync_method == "timestamp_nearest" else None
            ),
            tolerance_ns=lidar.tolerance_ns,
        )
    return results


def _selected_source_paths(
    request: DatasetSetupRequest,
    source_root: Path,
    config_root: Path,
) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for lidar in request.lidars:
        paths.update(_sample_paths(source_root, lidar.candidate))
        if lidar.timestamp is not None:
            paths.add(_safe_under(source_root, lidar.timestamp.relative_path))
    if request.camera is not None:
        paths.update(_sample_paths(source_root, request.camera.candidate))
        if request.camera.timestamp is not None:
            paths.add(_safe_under(source_root, request.camera.timestamp.relative_path))
        if request.camera.calibration_path is not None:
            paths.add(_safe_under(config_root, request.camera.calibration_path))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise DatasetSetupError(f"selected source file is missing: {missing[0]}")
    return tuple(sorted(paths, key=lambda path: str(path).encode("utf-8")))


def _validate_point_candidates(
    request: DatasetSetupRequest,
    source_root: Path,
) -> None:
    bin_loader = BinaryPointCloudLoader()
    pcd_loader = PcdPointCloudLoader()
    for lidar in request.lidars:
        spec = PointCloudSpec(
            columns=lidar.point_columns,
            source_frame=lidar.coordinate_frame,
            dtype=lidar.point_dtype,
            byte_order=lidar.byte_order,
        )
        sample_count = len(lidar.candidate.samples)
        representative_indices = sorted({0, sample_count // 2, sample_count - 1})
        loader = pcd_loader if lidar.candidate.format == "pcd" else bin_loader
        for index in representative_indices:
            sample = lidar.candidate.samples[index]
            path = _safe_under(source_root, sample.relative_path)
            try:
                cloud = loader.load(
                    path,
                    spec,
                    sensor_id=lidar.sensor_id,
                    return_id="1",
                )
            except (OSError, TypeError, ValueError) as exc:
                raise DatasetSetupError(
                    f"cannot load representative LiDAR sample {path}: {exc}"
                ) from exc
            if cloud.point_count == 0:
                raise DatasetSetupError(
                    f"representative LiDAR sample has no usable XYZ points: {path}"
                )


def _sample_paths(root: Path, candidate: SensorCandidate) -> tuple[Path, ...]:
    return tuple(_safe_under(root, sample.relative_path) for sample in candidate.samples)


def _load_timestamp_tables(
    request: DatasetSetupRequest,
    source_root: Path,
) -> dict[tuple[str, str], TimestampTable]:
    tables: dict[tuple[str, str], TimestampTable] = {}
    for lidar in request.lidars:
        if lidar.timestamp is not None:
            tables[("lidar", lidar.sensor_id)] = _read_timestamp_setup(
                source_root, lidar.timestamp
            )
    if request.camera is not None and request.camera.timestamp is not None:
        tables[("camera", request.camera.sensor_id)] = _read_timestamp_setup(
            source_root, request.camera.timestamp
        )
    return tables


def _read_timestamp_setup(root: Path, setup: TimestampSetup) -> TimestampTable:
    return read_timestamp_table(
        _safe_under(root, setup.relative_path),
        sample_id_column=setup.sample_id_column,
        value_column=setup.value_column,
        unit=setup.unit,
        clock_domain=setup.clock_domain,
        offset_ns=setup.offset_ns,
    )


def _manifest_document(
    request: DatasetSetupRequest,
    *,
    source_root: Path,
    config_root: Path,
    timestamp_tables: Mapping[tuple[str, str], TimestampTable],
    index_metadata: Mapping[str, tuple[str, str, int]],
    taxonomy_sha256: str,
    source_inventory_sha256: str,
    generation_name: str,
) -> dict[str, Any]:
    dataset_id = request.dataset_id or new_dataset_id()
    camera_document: dict[str, Any] | None = None
    if request.camera is not None:
        camera_document = {
            "id": request.camera.sensor_id,
            "display_name": request.camera.display_name,
            "coordinate_frame": request.camera.coordinate_frame,
            "image_pattern": request.camera.candidate.data_pattern,
        }
        timestamp = timestamp_tables.get(("camera", request.camera.sensor_id))
        if request.camera.timestamp is not None and timestamp is not None:
            camera_document["timestamp"] = _timestamp_document(
                request.camera.timestamp, timestamp.path
            )

    lidar_documents: list[dict[str, Any]] = []
    profile_documents: list[dict[str, Any]] = []
    for lidar in request.lidars:
        lidar_document: dict[str, Any] = {
            "id": lidar.sensor_id,
            "display_name": lidar.display_name,
            "coordinate_frame": lidar.coordinate_frame,
            "format": lidar.candidate.format,
            "data_pattern": lidar.candidate.data_pattern,
            "point_columns": list(lidar.point_columns),
        }
        if lidar.candidate.format == "bin":
            lidar_document["point_dtype"] = lidar.point_dtype
            lidar_document["byte_order"] = lidar.byte_order
        timestamp = timestamp_tables.get(("lidar", lidar.sensor_id))
        if lidar.timestamp is not None and timestamp is not None:
            lidar_document["timestamp"] = _timestamp_document(
                lidar.timestamp, timestamp.path
            )
        lidar_documents.append(lidar_document)
        index_path, index_sha256, frame_count = index_metadata[lidar.profile_id]
        profile_camera = None
        if request.camera is not None and lidar.sync_method != "lidar_only":
            calibration_sha256 = None
            if request.camera.calibration_path is not None:
                calibration_sha256 = _sha256(
                    _safe_under(config_root, request.camera.calibration_path)
                )
            profile_camera = {
                "camera_id": request.camera.sensor_id,
                "mode": request.camera.mode,
                "calibration_path": request.camera.calibration_path,
                "calibration_sha256": calibration_sha256,
            }
        profile_documents.append(
            {
                "id": lidar.profile_id,
                "display_name": lidar.profile_display_name,
                "lidar_id": lidar.sensor_id,
                "camera": profile_camera,
                "frame_index": {
                    "schema_version": "2.0",
                    "path": index_path,
                    "sha256": index_sha256,
                    "frame_count": frame_count,
                    "generation": {
                        "method": lidar.sync_method,
                        "tolerance_ns": lidar.tolerance_ns,
                    },
                },
            }
        )
    return {
        "schema_version": "2.0",
        "dataset_id": dataset_id,
        "display_name": request.display_name.strip(),
        "manifest_revision": 1,
        "layout": "device_centric_v2",
        "data_root": (
            {"kind": "manifest_relative", "path": "."}
            if source_root == config_root
            else {"kind": "absolute_local", "path": str(source_root)}
        ),
        "coordinate_system": {
            "unit": "meter",
            "x_axis": "forward",
            "y_axis": "left",
            "z_axis": "up",
            "yaw_axis": "+z",
            "yaw_unit": "radian",
            "yaw_zero": "+x",
            "yaw_direction": "counterclockwise",
            "box_center": "geometric_center",
        },
        "labeling_policy": {
            "active_lidar": "one_per_profile",
            "merge_lidars": False,
            "label_namespace": "profile_lidar",
            "frame_id_policy": "logical_lidar_sample_id",
        },
        "lidars": lidar_documents,
        "camera": camera_document,
        "profiles": profile_documents,
        "default_profile_id": request.default_profile_id or request.lidars[0].profile_id,
        "taxonomy": {
            "schema_version": "2.0",
            "path": f"generations/{generation_name}/taxonomy.json",
            "sha256": taxonomy_sha256,
        },
        "metadata": {
            "created_at_utc": _utc_now(),
            "source_inventory_sha256": source_inventory_sha256,
            "setup_service": "generic_dataset_v2",
        },
    }


def _timestamp_document(setup: TimestampSetup, path: Path) -> dict[str, Any]:
    return {
        "format": "csv",
        "path": setup.relative_path,
        "sample_id_column": setup.sample_id_column,
        "value_column": setup.value_column,
        "unit": setup.unit,
        "clock_domain": setup.clock_domain,
        "offset_ns": setup.offset_ns,
        "sha256": _sha256(path),
    }


def _hash_paths(
    paths: tuple[Path, ...],
    *,
    phase: str,
    progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> dict[Path, str]:
    result: dict[Path, str] = {}
    for position, path in enumerate(paths, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress(phase, position, len(paths), str(path))
        result[path] = _sha256(path)
    return result


def _inventory_hash(root: Path, hashes: Mapping[Path, str]) -> str:
    rows = [
        {
            "path": (
                path.relative_to(root).as_posix()
                if path.is_relative_to(root)
                else str(path)
            ),
            "sha256": digest,
        }
        for path, digest in hashes.items()
    ]
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_under(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise DatasetSetupError(f"unsafe relative path: {value}")
    candidate = root.joinpath(*pure.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetSetupError(f"path escapes configured root: {value}") from exc
    return candidate


def _write_json_fsynced(path: Path, document: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    _write_bytes_fsynced(path, payload)


def _write_bytes_fsynced(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _machine_id_from_display(value: str, prefix: str, used: set[str]) -> str:
    parts = re.findall(r"[a-z0-9]+", value.casefold())
    base = "_".join(parts).strip("._-") or prefix
    candidate = base[:64].rstrip(".")
    if not _MACHINE_ID.fullmatch(candidate) or candidate in used:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        candidate = f"{prefix}_{digest}"
    if candidate in used:
        raise DatasetSetupError(f"cannot generate unique machine ID for {value!r}")
    return candidate


def _require_machine_id(value: str, name: str) -> None:
    if not _MACHINE_ID.fullmatch(value):
        raise DatasetSetupError(f"{name} is not a safe machine ID: {value!r}")


def _remove_owned_manifest(path: Path, expected_payload: bytes) -> bool:
    """Remove only the manifest bytes created by this setup transaction."""
    if path.name != "dataset.json":
        raise RuntimeError(f"refusing to remove unexpected manifest path: {path}")
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if current != expected_payload:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _remove_owned_generation(path: Path, parent: Path, expected_name: str) -> None:
    if path.parent != parent or path.name != expected_name:
        raise RuntimeError(f"refusing to remove unexpected generation path: {path}")
    if path.exists():
        shutil.rmtree(path)


def _remove_owned_temporary(path: Path, config_root: Path) -> None:
    if not path.exists():
        return
    resolved_parent = path.parent.resolve()
    allowed = {config_root.resolve(), (config_root / "generations").resolve()}
    if resolved_parent not in allowed or not path.name.startswith("."):
        raise RuntimeError(f"refusing to remove unexpected temporary path: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise DatasetSetupCancelled("dataset setup was cancelled")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
