from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Callable, Mapping, cast
from uuid import uuid4

from lidar_label_tool.domain.dataset_v2 import (
    DatasetManifestV2,
    FrameIndexRecordV2,
    SyncMethod,
    TimestampSpecV2,
)
from lidar_label_tool.domain.label_identity_v2 import lidar_binding_sha256
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.dataset_v2 import (
    canonical_frame_index_bytes,
    parse_dataset_manifest_v2,
)
from lidar_label_tool.io.json_schema import read_json_document
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.dataset_v2_validation import (
    DatasetV2ValidationReport,
    validate_dataset_manifest_v2,
    validate_dataset_v2,
)
from lidar_label_tool.services.recovery_v2 import V2RecoveryStore
from lidar_label_tool.services.timestamp_synchronizer import (
    SensorSample,
    SynchronizationQa,
    SynchronizationResult,
    make_sensor_samples,
    synchronize_profile,
)
from lidar_label_tool.services.timestamp_table import TimestampTable, read_timestamp_table


class DatasetResyncError(ValueError):
    pass


class DatasetResyncConflictError(DatasetResyncError):
    pass


class DatasetResyncCancelled(DatasetResyncError):
    pass


ProgressCallback = Callable[[str, int, int, str], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class DatasetResyncRequest:
    config_root: Path
    profile_id: str
    method: SyncMethod | None = None
    tolerance_ns: int | None = None
    expected_manifest_sha256: str | None = None
    expected_source_inventory_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetResyncProfileAnalysis:
    profile_id: str
    method: SyncMethod
    tolerance_ns: int | None
    qa: SynchronizationQa
    camera_binding_change_count: int
    frame_order_change_count: int


@dataclass(frozen=True, slots=True)
class DatasetResyncAnalysis:
    config_root: Path
    target_profile_id: str
    current_manifest_revision: int
    next_manifest_revision: int
    manifest_sha256: str
    source_inventory_sha256: str
    profiles: tuple[DatasetResyncProfileAnalysis, ...]

    @property
    def target(self) -> DatasetResyncProfileAnalysis:
        return next(item for item in self.profiles if item.profile_id == self.target_profile_id)


@dataclass(frozen=True, slots=True)
class DatasetResyncResult:
    config_root: Path
    profile_id: str
    manifest_revision: int
    generation_path: Path
    qa: SynchronizationQa
    validation: DatasetV2ValidationReport


def analyze_dataset_resync_v2(
    request: DatasetResyncRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetResyncAnalysis:
    """Build a read-only deterministic preview of every profile's next index."""
    config_root = Path(request.config_root).resolve()
    _check_cancel(cancel_check)
    manifest_path = config_root / "dataset.json"
    baseline_sha256 = _sha256(manifest_path)
    if (
        request.expected_manifest_sha256 is not None
        and request.expected_manifest_sha256 != baseline_sha256
    ):
        raise DatasetResyncConflictError(
            "dataset.json changed after resync analysis; reload before applying"
        )
    document = read_json_document(manifest_path)
    if not isinstance(document, Mapping):
        raise DatasetResyncError("dataset.json root must be an object")
    manifest = parse_dataset_manifest_v2(document)
    profile = manifest.profile(request.profile_id)
    if profile is None:
        raise DatasetResyncError(f"unknown v2 profile: {request.profile_id}")
    adapters, results, settings = _synchronize_all_profiles(
        config_root,
        manifest,
        target_profile_id=profile.id,
        target_method=request.method,
        target_tolerance_ns=request.tolerance_ns,
        progress=progress,
        cancel_check=cancel_check,
    )
    inventory_sha256 = _sync_source_inventory_sha256(
        manifest,
        adapters,
        progress=progress,
        cancel_check=cancel_check,
    )
    if (
        request.expected_source_inventory_sha256 is not None
        and request.expected_source_inventory_sha256 != inventory_sha256
    ):
        raise DatasetResyncConflictError(
            "source files changed after resync analysis; analyze again before applying"
        )
    profiles = tuple(
        _profile_analysis(
            profile_id=item.id,
            adapter=adapters[item.id],
            result=results[item.id],
            method=settings[item.id][0],
            tolerance_ns=settings[item.id][1],
        )
        for item in manifest.profiles
    )
    return DatasetResyncAnalysis(
        config_root=config_root,
        target_profile_id=profile.id,
        current_manifest_revision=manifest.manifest_revision,
        next_manifest_revision=manifest.manifest_revision + 1,
        manifest_sha256=baseline_sha256,
        source_inventory_sha256=inventory_sha256,
        profiles=profiles,
    )


def resynchronize_dataset_v2(
    request: DatasetResyncRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetResyncResult:
    """Rebuild all generation files while preserving the target LiDAR bindings."""
    config_root = Path(request.config_root).resolve()
    _check_cancel(cancel_check)
    manifest_path = config_root / "dataset.json"
    baseline_sha256 = _sha256(manifest_path)
    if (
        request.expected_manifest_sha256 is not None
        and request.expected_manifest_sha256 != baseline_sha256
    ):
        raise DatasetResyncConflictError(
            "dataset.json changed after resync analysis; reload before applying"
        )
    document = read_json_document(manifest_path)
    if not isinstance(document, Mapping):
        raise DatasetResyncError("dataset.json root must be an object")
    manifest_document = cast(dict[str, Any], deepcopy(document))
    manifest = parse_dataset_manifest_v2(manifest_document)
    profile = manifest.profile(request.profile_id)
    if profile is None:
        raise DatasetResyncError(f"unknown v2 profile: {request.profile_id}")
    adapters, results, generation_settings = _synchronize_all_profiles(
        config_root,
        manifest,
        target_profile_id=profile.id,
        target_method=request.method,
        target_tolerance_ns=request.tolerance_ns,
        progress=progress,
        cancel_check=cancel_check,
    )
    adapter = adapters[profile.id]
    result = results[profile.id]
    source_inventory_sha256 = _sync_source_inventory_sha256(
        manifest,
        adapters,
        progress=progress,
        cancel_check=cancel_check,
    )
    if (
        request.expected_source_inventory_sha256 is not None
        and request.expected_source_inventory_sha256 != source_inventory_sha256
    ):
        raise DatasetResyncConflictError(
            "source files changed after resync analysis; analyze again before applying"
        )

    next_revision = manifest.manifest_revision + 1
    generation_name = f"generation-{next_revision:06d}"
    generations_root = config_root / "generations"
    generation_path = generations_root / generation_name
    token = uuid4().hex
    staging_path = generations_root / f".{generation_name}.{token}.tmp"
    manifest_temporary = config_root / f".dataset.json.{token}.tmp"
    old_manifest_bytes = manifest_path.read_bytes()
    generation_activated = False
    manifest_committed = False
    try:
        if generation_path.exists():
            raise DatasetResyncConflictError(
                f"new generation path already exists: {generation_path}"
            )
        (staging_path / "sync").mkdir(parents=True, exist_ok=False)
        _check_cancel(cancel_check)
        old_taxonomy = _config_path(config_root, manifest.taxonomy.path)
        taxonomy_bytes = old_taxonomy.read_bytes()
        _write_bytes(staging_path / "taxonomy.json", taxonomy_bytes)
        taxonomy_sha256 = hashlib.sha256(taxonomy_bytes).hexdigest()

        target_profiles = cast(list[dict[str, Any]], manifest_document["profiles"])
        by_id = {str(item["id"]): item for item in target_profiles}
        for existing_profile in manifest.profiles:
            records = results[existing_profile.id].records
            generation_method, generation_tolerance = generation_settings[
                existing_profile.id
            ]
            payload = canonical_frame_index_bytes(records)
            relative = f"generations/{generation_name}/sync/{existing_profile.id}.frames.jsonl"
            _write_bytes(staging_path / "sync" / f"{existing_profile.id}.frames.jsonl", payload)
            profile_document = by_id[existing_profile.id]
            profile_document["frame_index"] = {
                "schema_version": "2.0",
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "frame_count": len(records),
                "generation": {
                    "method": generation_method,
                    "tolerance_ns": generation_tolerance,
                },
            }
            if generation_method == "lidar_only":
                profile_document["camera"] = None
            elif profile_document.get("camera") is None:
                assert manifest.camera is not None
                profile_document["camera"] = {
                    "camera_id": manifest.camera.id,
                    "mode": "display_only",
                    "calibration_path": None,
                    "calibration_sha256": None,
                }

        manifest_document["manifest_revision"] = next_revision
        manifest_document["taxonomy"] = {
            "schema_version": "2.0",
            "path": f"generations/{generation_name}/taxonomy.json",
            "sha256": taxonomy_sha256,
        }
        _refresh_timestamp_hashes(manifest_document, adapter.data_root)
        if _sync_source_inventory_sha256(
            manifest,
            adapters,
            progress=progress,
            cancel_check=cancel_check,
        ) != source_inventory_sha256:
            raise DatasetResyncConflictError(
                "source files changed while the new sync generation was built"
            )
        _check_cancel(cancel_check)
        os.replace(staging_path, generation_path)
        generation_activated = True
        candidate = parse_dataset_manifest_v2(manifest_document)
        validate_dataset_manifest_v2(config_root, candidate).require_valid()
        if _sha256(manifest_path) != baseline_sha256:
            raise DatasetResyncConflictError(
                "dataset.json changed while the new sync generation was built"
            )
        _write_json(manifest_temporary, manifest_document)
        parse_dataset_manifest_v2(read_json_document(manifest_temporary))
        _check_cancel(cancel_check)
        os.replace(manifest_temporary, manifest_path)
        manifest_committed = True
        final_report = validate_dataset_v2(config_root)
        final_report.require_valid()
        return DatasetResyncResult(
            config_root=config_root,
            profile_id=profile.id,
            manifest_revision=next_revision,
            generation_path=generation_path,
            qa=result.qa,
            validation=final_report,
        )
    except Exception:
        if manifest_committed:
            _restore_manifest(manifest_path, old_manifest_bytes, token)
            manifest_committed = False
        if generation_activated:
            _remove_generation(generation_path, generations_root, generation_name)
        raise
    finally:
        _remove_temporary(manifest_temporary, config_root)
        _remove_temporary(staging_path, config_root)


def _synchronize_all_profiles(
    config_root: Path,
    manifest: DatasetManifestV2,
    *,
    target_profile_id: str,
    target_method: SyncMethod | None,
    target_tolerance_ns: int | None,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[
    dict[str, DeviceCentricV2Adapter],
    dict[str, SynchronizationResult],
    dict[str, tuple[SyncMethod, int | None]],
]:
    adapters: dict[str, DeviceCentricV2Adapter] = {}
    results: dict[str, SynchronizationResult] = {}
    settings: dict[str, tuple[SyncMethod, int | None]] = {}
    camera_samples: tuple[SensorSample, ...] | None = None
    camera_timestamps: TimestampTable | None = None

    for position, profile in enumerate(manifest.profiles, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress("synchronize", position, len(manifest.profiles), profile.id)
        adapter = DeviceCentricV2Adapter(config_root, profile.id)
        adapter.scan()
        _validate_existing_work(adapter)
        adapters[profile.id] = adapter

        method = (
            target_method
            if profile.id == target_profile_id and target_method is not None
            else profile.frame_index.generation.method
        )
        tolerance = (
            target_tolerance_ns
            if profile.id == target_profile_id and target_tolerance_ns is not None
            else profile.frame_index.generation.tolerance_ns
        )
        if method != "timestamp_nearest":
            tolerance = None
        if method != "lidar_only":
            if manifest.camera is None:
                raise DatasetResyncError(
                    f"profile {profile.id!r} requests camera sync but no camera is configured"
                )
            if camera_samples is None:
                camera_samples = _samples_from_pattern(
                    adapter.data_root,
                    manifest.camera.id,
                    manifest.camera.image_pattern,
                )
                camera_timestamps = _timestamp_table(
                    adapter.data_root,
                    manifest.camera.timestamp,
                )

        lidar_samples = tuple(
            SensorSample(
                sensor_id=record.lidar.sensor_id,
                source_sample_id=record.lidar.source_sample_id,
                relative_path=record.lidar.path,
                logical_sample_id=record.lidar.sample_id,
            )
            for record in (
                adapter.frame_record(frame_id) for frame_id in adapter.index.frame_ids
            )
        )
        result = synchronize_profile(
            profile_id=profile.id,
            lidar_samples=lidar_samples,
            method=method,
            camera_samples=(camera_samples or ()),
            lidar_timestamps=_timestamp_table(
                adapter.data_root,
                adapter.active_lidar.timestamp,
            ),
            camera_timestamps=(
                camera_timestamps if method == "timestamp_nearest" else None
            ),
            tolerance_ns=tolerance,
        )
        _require_same_lidar_bindings(adapter, result.records)
        results[profile.id] = result
        settings[profile.id] = (method, tolerance)
    return adapters, results, settings


def _profile_analysis(
    *,
    profile_id: str,
    adapter: DeviceCentricV2Adapter,
    result: SynchronizationResult,
    method: SyncMethod,
    tolerance_ns: int | None,
) -> DatasetResyncProfileAnalysis:
    old_records = {
        frame_id: adapter.frame_record(frame_id) for frame_id in adapter.index.frame_ids
    }
    new_records = {record.frame_id: record for record in result.records}
    camera_changes = sum(
        _camera_binding(old_records[frame_id]) != _camera_binding(new_records[frame_id])
        for frame_id in old_records
    )
    old_order = adapter.index.frame_ids
    new_order = tuple(record.frame_id for record in result.records)
    order_changes = sum(old != new for old, new in zip(old_order, new_order, strict=True))
    return DatasetResyncProfileAnalysis(
        profile_id=profile_id,
        method=method,
        tolerance_ns=tolerance_ns,
        qa=result.qa,
        camera_binding_change_count=camera_changes,
        frame_order_change_count=order_changes,
    )


def _camera_binding(record: FrameIndexRecordV2) -> object:
    return record.camera.to_dict() if record.camera is not None else None


def _sync_source_inventory_sha256(
    manifest: DatasetManifestV2,
    adapters: Mapping[str, DeviceCentricV2Adapter],
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> str:
    paths: dict[str, Path] = {}
    for profile_id, adapter in adapters.items():
        for frame_id in adapter.index.frame_ids:
            relative = adapter.frame_record(frame_id).lidar.path
            paths[f"data:{relative}"] = _data_path(adapter.data_root, relative)
        camera = adapter.profile.camera
        if camera is not None and camera.calibration_path is not None:
            paths[f"config:{camera.calibration_path}"] = _config_path(
                adapter.configuration_root,
                camera.calibration_path,
            )
        paths[f"index:{profile_id}"] = _config_path(
            adapter.configuration_root,
            adapter.profile.frame_index.path,
        )

    first_adapter = next(iter(adapters.values()))
    data_root = first_adapter.data_root
    config_root = first_adapter.configuration_root
    for lidar in manifest.lidars:
        if lidar.timestamp is not None:
            paths[f"data:{lidar.timestamp.path}"] = _data_path(
                data_root,
                lidar.timestamp.path,
            )
    if manifest.camera is not None:
        if manifest.camera.timestamp is not None:
            paths[f"data:{manifest.camera.timestamp.path}"] = _data_path(
                data_root,
                manifest.camera.timestamp.path,
            )
        for path in _paths_from_pattern(data_root, manifest.camera.image_pattern):
            relative = path.relative_to(data_root).as_posix()
            paths[f"data:{relative}"] = path
    paths[f"config:{manifest.taxonomy.path}"] = _config_path(
        config_root,
        manifest.taxonomy.path,
    )
    rows: list[tuple[str, str]] = []
    ordered_paths = sorted(paths.items())
    for position, (key, path) in enumerate(ordered_paths, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress("fingerprint", position, len(ordered_paths), key)
        rows.append((key, _sha256(path)))
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _paths_from_pattern(root: Path, pattern: str) -> tuple[Path, ...]:
    if pattern.count("{sample_id}") != 1:
        raise DatasetResyncError(f"camera pattern is invalid: {pattern}")
    prefix, suffix = pattern.split("{sample_id}")
    return tuple(
        path
        for path in sorted(
            root.glob(prefix + "*" + suffix),
            key=lambda item: item.relative_to(root).as_posix().encode("utf-8"),
        )
        if path.is_file()
    )


def _validate_existing_work(adapter: DeviceCentricV2Adapter) -> None:
    repository = V2LabelRepository.for_sidecar(adapter)
    recovery = V2RecoveryStore(repository)
    for frame_id in adapter.index.frame_ids:
        if repository.exists(frame_id):
            repository.load(frame_id)
        recovery_result = recovery.inspect(frame_id)
        if recovery_result.error:
            raise DatasetResyncError(
                f"cannot resync with an invalid recovery snapshot: {frame_id}: "
                f"{recovery_result.error}"
            )


def _require_same_lidar_bindings(
    adapter: DeviceCentricV2Adapter,
    records: tuple[Any, ...],
) -> None:
    old = {
        frame_id: lidar_binding_sha256(adapter.frame_record(frame_id))
        for frame_id in adapter.index.frame_ids
    }
    new = {record.frame_id: lidar_binding_sha256(record) for record in records}
    if old != new:
        raise DatasetResyncError(
            "resynchronization attempted to change a frozen frame-to-LiDAR binding"
        )


def _samples_from_pattern(
    data_root: Path,
    sensor_id: str,
    pattern: str,
) -> tuple[SensorSample, ...]:
    if pattern.count("{sample_id}") != 1:
        raise DatasetResyncError(f"camera pattern is invalid: {pattern}")
    prefix, suffix = pattern.split("{sample_id}")
    paths = sorted(
        data_root.glob(prefix + "*" + suffix),
        key=lambda path: path.relative_to(data_root).as_posix().encode("utf-8"),
    )
    source_samples: list[tuple[str, str]] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(data_root).as_posix()
        end = len(relative) - len(suffix) if suffix else len(relative)
        source_samples.append((relative[len(prefix) : end], relative))
    if not source_samples:
        raise DatasetResyncError("camera pattern found no image samples")
    return make_sensor_samples(sensor_id, source_samples)


def _timestamp_table(root: Path, spec: TimestampSpecV2 | None) -> TimestampTable | None:
    if spec is None:
        return None
    return read_timestamp_table(
        _data_path(root, spec.path),
        sample_id_column=spec.sample_id_column,
        value_column=spec.value_column,
        unit=spec.unit,  # type: ignore[arg-type]
        clock_domain=spec.clock_domain,
        offset_ns=spec.offset_ns,
    )


def _refresh_timestamp_hashes(document: dict[str, Any], data_root: Path) -> None:
    for lidar in cast(list[dict[str, Any]], document["lidars"]):
        timestamp = lidar.get("timestamp")
        if isinstance(timestamp, dict):
            timestamp["sha256"] = _sha256(_data_path(data_root, str(timestamp["path"])))
    camera = document.get("camera")
    if isinstance(camera, dict) and isinstance(camera.get("timestamp"), dict):
        camera["timestamp"]["sha256"] = _sha256(
            _data_path(data_root, str(camera["timestamp"]["path"]))
        )


def _data_path(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise DatasetResyncError(f"unsafe data path: {value}")
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetResyncError(f"data path escapes root: {value}") from exc
    return path


def _config_path(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise DatasetResyncError(f"unsafe config path: {value}")
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetResyncError(f"config path escapes root: {value}") from exc
    return path


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    _write_bytes(
        path,
        (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        ),
    )


def _restore_manifest(path: Path, payload: bytes, token: str) -> None:
    temporary = path.with_name(f".dataset.json.{token}.restore.tmp")
    try:
        _write_bytes(temporary, payload)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _remove_generation(path: Path, parent: Path, expected_name: str) -> None:
    if path.parent != parent or path.name != expected_name:
        raise RuntimeError(f"refusing to remove unexpected generation path: {path}")
    if path.exists():
        shutil.rmtree(path)


def _remove_temporary(path: Path, config_root: Path) -> None:
    if not path.exists():
        return
    if path.parent.resolve() not in {
        config_root.resolve(),
        (config_root / "generations").resolve(),
    } or not path.name.startswith("."):
        raise RuntimeError(f"refusing to remove unexpected temporary path: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise DatasetResyncCancelled("dataset resynchronization was cancelled")
