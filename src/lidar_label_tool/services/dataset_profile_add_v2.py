from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Callable, Mapping, cast
from uuid import uuid4

from lidar_label_tool.domain.dataset_v2 import DatasetManifestV2
from lidar_label_tool.domain.point_cloud import PointCloudSpec
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.dataset_v2 import (
    canonical_frame_index_bytes,
    parse_dataset_manifest_v2,
)
from lidar_label_tool.io.json_schema import read_json_document
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader
from lidar_label_tool.io.loaders.pcd_loader import PcdPointCloudLoader
from lidar_label_tool.services.dataset_setup import CameraSetup, LidarSetup, TimestampSetup
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


ProgressCallback = Callable[[str, int, int, str], None]
CancelCheck = Callable[[], bool]
_MACHINE_ID = re.compile(
    r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))"
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$"
)


class DatasetProfileAddError(ValueError):
    pass


class DatasetProfileAddConflictError(DatasetProfileAddError):
    pass


class DatasetProfileAddCancelled(DatasetProfileAddError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetProfileAddRequest:
    config_root: Path
    lidar: LidarSetup
    camera: CameraSetup | None
    coordinate_system_confirmed: bool
    expected_manifest_sha256: str | None = None
    expected_source_inventory_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetProfileAddAnalysis:
    config_root: Path
    data_root: Path
    dataset_id: str
    current_manifest_revision: int
    next_manifest_revision: int
    profile_id: str
    manifest_sha256: str
    source_inventory_sha256: str
    source_file_count: int
    existing_label_count: int
    qa: SynchronizationQa


@dataclass(frozen=True, slots=True)
class DatasetProfileAddResult:
    config_root: Path
    dataset_id: str
    profile_id: str
    manifest_revision: int
    generation_path: Path
    qa: SynchronizationQa
    validation: DatasetV2ValidationReport


@dataclass(frozen=True, slots=True)
class _PreparedAddition:
    config_root: Path
    data_root: Path
    manifest_path: Path
    manifest_document: dict[str, Any]
    manifest: DatasetManifestV2
    manifest_sha256: str
    source_paths: tuple[tuple[str, Path], ...]
    source_inventory_sha256: str
    existing_adapters: tuple[DeviceCentricV2Adapter, ...]
    existing_label_count: int
    sync_result: SynchronizationResult


def analyze_dataset_profile_add_v2(
    request: DatasetProfileAddRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetProfileAddAnalysis:
    """Analyze a new LiDAR profile without changing the configuration or source."""
    prepared = _prepare_addition(
        request,
        progress=progress,
        cancel_check=cancel_check,
    )
    return DatasetProfileAddAnalysis(
        config_root=prepared.config_root,
        data_root=prepared.data_root,
        dataset_id=prepared.manifest.dataset_id,
        current_manifest_revision=prepared.manifest.manifest_revision,
        next_manifest_revision=prepared.manifest.manifest_revision + 1,
        profile_id=request.lidar.profile_id,
        manifest_sha256=prepared.manifest_sha256,
        source_inventory_sha256=prepared.source_inventory_sha256,
        source_file_count=len(prepared.source_paths),
        existing_label_count=prepared.existing_label_count,
        qa=prepared.sync_result.qa,
    )


def add_dataset_profile_v2(
    request: DatasetProfileAddRequest,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetProfileAddResult:
    """Commit one new LiDAR profile while preserving every existing identity."""
    if request.expected_manifest_sha256 is None:
        raise DatasetProfileAddConflictError(
            "profile addition requires a fresh read-only analysis"
        )
    if request.expected_source_inventory_sha256 is None:
        raise DatasetProfileAddConflictError(
            "profile addition requires the analyzed source inventory fingerprint"
        )
    prepared = _prepare_addition(
        request,
        progress=progress,
        cancel_check=cancel_check,
    )
    next_revision = prepared.manifest.manifest_revision + 1
    generation_name = f"generation-{next_revision:06d}"
    generations_root = prepared.config_root / "generations"
    generation_path = generations_root / generation_name
    token = uuid4().hex
    staging_path = generations_root / f".{generation_name}.{token}.tmp"
    manifest_temporary = prepared.config_root / f".dataset.json.{token}.tmp"
    old_manifest_bytes = prepared.manifest_path.read_bytes()
    generation_activated = False
    manifest_committed = False
    try:
        if generation_path.exists():
            raise DatasetProfileAddConflictError(
                f"new generation path already exists: {generation_path}"
            )
        (staging_path / "sync").mkdir(parents=True, exist_ok=False)
        _check_cancel(cancel_check)

        taxonomy_source = _config_path(
            prepared.config_root,
            prepared.manifest.taxonomy.path,
        )
        taxonomy_bytes = taxonomy_source.read_bytes()
        _write_bytes(staging_path / "taxonomy.json", taxonomy_bytes)
        taxonomy_sha256 = hashlib.sha256(taxonomy_bytes).hexdigest()

        document = cast(dict[str, Any], deepcopy(prepared.manifest_document))
        profile_documents = cast(list[dict[str, Any]], document["profiles"])
        profiles_by_id = {str(item["id"]): item for item in profile_documents}
        for position, adapter in enumerate(prepared.existing_adapters, start=1):
            _check_cancel(cancel_check)
            source = _config_path(
                prepared.config_root,
                adapter.profile.frame_index.path,
            )
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != adapter.profile.frame_index.sha256:
                raise DatasetProfileAddConflictError(
                    f"existing frame index changed: {adapter.profile.id}"
                )
            target_name = f"{adapter.profile.id}.frames.jsonl"
            _write_bytes(staging_path / "sync" / target_name, payload)
            profiles_by_id[adapter.profile.id]["frame_index"]["path"] = (
                f"generations/{generation_name}/sync/{target_name}"
            )
            if progress is not None:
                progress(
                    "copy_existing_profiles",
                    position,
                    len(prepared.existing_adapters),
                    adapter.profile.id,
                )

        new_index_bytes = canonical_frame_index_bytes(prepared.sync_result.records)
        new_index_name = f"{request.lidar.profile_id}.frames.jsonl"
        _write_bytes(staging_path / "sync" / new_index_name, new_index_bytes)
        _append_lidar_and_profile(
            document,
            request,
            generation_name=generation_name,
            index_name=new_index_name,
            index_payload=new_index_bytes,
            data_root=prepared.data_root,
            camera_id=(
                prepared.manifest.camera.id
                if request.lidar.sync_method != "lidar_only"
                and prepared.manifest.camera is not None
                else None
            ),
        )
        document["manifest_revision"] = next_revision
        document["taxonomy"] = {
            "schema_version": "2.0",
            "path": f"generations/{generation_name}/taxonomy.json",
            "sha256": taxonomy_sha256,
        }
        metadata = cast(dict[str, Any], document.setdefault("metadata", {}))
        metadata["last_reconfigured_at_utc"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        metadata["last_reconfiguration"] = "add_lidar_profile"
        metadata["source_inventory_sha256"] = prepared.source_inventory_sha256

        if _inventory_sha256(
            prepared.source_paths,
            progress=progress,
            cancel_check=cancel_check,
        ) != prepared.source_inventory_sha256:
            raise DatasetProfileAddConflictError(
                "source files changed while the profile generation was built"
            )
        if _sha256(prepared.manifest_path) != prepared.manifest_sha256:
            raise DatasetProfileAddConflictError(
                "dataset.json changed while the profile generation was built"
            )
        _check_cancel(cancel_check)
        os.replace(staging_path, generation_path)
        generation_activated = True
        candidate = parse_dataset_manifest_v2(document)
        validate_dataset_manifest_v2(prepared.config_root, candidate).require_valid()
        _write_json(manifest_temporary, document)
        parse_dataset_manifest_v2(read_json_document(manifest_temporary))
        _check_cancel(cancel_check)
        os.replace(manifest_temporary, prepared.manifest_path)
        manifest_committed = True
        final_report = validate_dataset_v2(prepared.config_root)
        final_report.require_valid()
        _verify_existing_labels(prepared.existing_adapters)
        return DatasetProfileAddResult(
            config_root=prepared.config_root,
            dataset_id=prepared.manifest.dataset_id,
            profile_id=request.lidar.profile_id,
            manifest_revision=next_revision,
            generation_path=generation_path,
            qa=prepared.sync_result.qa,
            validation=final_report,
        )
    except Exception:
        if manifest_committed:
            _restore_manifest(prepared.manifest_path, old_manifest_bytes, token)
            manifest_committed = False
        if generation_activated:
            _remove_generation(generation_path, generations_root, generation_name)
        raise
    finally:
        _remove_temporary(manifest_temporary, prepared.config_root)
        _remove_temporary(staging_path, prepared.config_root)


def _prepare_addition(
    request: DatasetProfileAddRequest,
    *,
    progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> _PreparedAddition:
    config_root = Path(request.config_root).resolve()
    manifest_path = config_root / "dataset.json"
    manifest_sha256 = _sha256(manifest_path)
    if (
        request.expected_manifest_sha256 is not None
        and request.expected_manifest_sha256 != manifest_sha256
    ):
        raise DatasetProfileAddConflictError(
            "dataset.json changed after profile-add analysis; analyze again"
        )
    report = validate_dataset_v2(config_root, verify_images=False)
    report.require_valid()
    manifest_document = read_json_document(manifest_path)
    if not isinstance(manifest_document, Mapping):
        raise DatasetProfileAddError("dataset.json root must be an object")
    document = cast(dict[str, Any], manifest_document)
    manifest = parse_dataset_manifest_v2(document)
    first_adapter = DeviceCentricV2Adapter(config_root, manifest.default_profile_id)
    first_adapter.scan()
    data_root = first_adapter.data_root
    _validate_request(request, manifest, data_root)
    _validate_representative_points(request.lidar, data_root)

    adapters = tuple(
        DeviceCentricV2Adapter(config_root, profile.id)
        for profile in manifest.profiles
    )
    for adapter in adapters:
        adapter.scan()
    existing_label_count = _verify_existing_labels(adapters)
    result = _synchronize_new_profile(request, manifest, data_root)
    source_paths = _source_paths(request, manifest, adapters, data_root, config_root)
    inventory_sha256 = _inventory_sha256(
        source_paths,
        progress=progress,
        cancel_check=cancel_check,
    )
    if (
        request.expected_source_inventory_sha256 is not None
        and request.expected_source_inventory_sha256 != inventory_sha256
    ):
        raise DatasetProfileAddConflictError(
            "source files changed after profile-add analysis; analyze again"
        )
    return _PreparedAddition(
        config_root=config_root,
        data_root=data_root,
        manifest_path=manifest_path,
        manifest_document=document,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        source_paths=source_paths,
        source_inventory_sha256=inventory_sha256,
        existing_adapters=adapters,
        existing_label_count=existing_label_count,
        sync_result=result,
    )


def _validate_request(
    request: DatasetProfileAddRequest,
    manifest: DatasetManifestV2,
    data_root: Path,
) -> None:
    lidar = request.lidar
    if not request.coordinate_system_confirmed:
        raise DatasetProfileAddError(
            "the new LiDAR coordinate system must be explicitly confirmed"
        )
    for name, value in (("lidar sensor_id", lidar.sensor_id), ("profile_id", lidar.profile_id)):
        if not _MACHINE_ID.fullmatch(value):
            raise DatasetProfileAddError(f"{name} is not a safe machine ID: {value!r}")
    if manifest.lidar(lidar.sensor_id) is not None:
        raise DatasetProfileAddError(f"LiDAR ID already exists: {lidar.sensor_id}")
    if manifest.profile(lidar.profile_id) is not None:
        raise DatasetProfileAddError(f"profile ID already exists: {lidar.profile_id}")
    if any(item.data_pattern == lidar.candidate.data_pattern for item in manifest.lidars):
        raise DatasetProfileAddError("the selected LiDAR files are already registered")
    if lidar.candidate.kind != "lidar" or not lidar.candidate.samples:
        raise DatasetProfileAddError("the selected LiDAR candidate is invalid")
    if not lidar.coordinate_frame.strip():
        raise DatasetProfileAddError("coordinate_frame is required")
    if len(lidar.point_columns) != len(set(lidar.point_columns)):
        raise DatasetProfileAddError("point columns must not contain duplicates")
    if not {"x", "y", "z"}.issubset(lidar.point_columns):
        raise DatasetProfileAddError("point columns require x/y/z")
    declared = lidar.candidate.declared_point_columns
    if declared and declared != lidar.point_columns:
        raise DatasetProfileAddError(
            "point columns do not match the selected sensor metadata"
        )
    if lidar.candidate.declared_point_dtype not in {None, "float32"}:
        raise DatasetProfileAddError("only metadata-declared float32 BIN is supported")
    for sample in lidar.candidate.samples:
        _data_path(data_root, sample.relative_path)
    if lidar.sync_method == "lidar_only":
        if request.camera is not None:
            raise DatasetProfileAddError("lidar_only must not select a camera")
        return
    if manifest.camera is None or request.camera is None:
        raise DatasetProfileAddError("camera sync requires the existing dataset camera")
    if request.camera.sensor_id != manifest.camera.id:
        raise DatasetProfileAddError("camera ID does not match the existing manifest")
    if request.camera.candidate.data_pattern != manifest.camera.image_pattern:
        raise DatasetProfileAddError("camera files do not match the existing manifest")
    if lidar.sync_method == "timestamp_nearest":
        if lidar.timestamp is None:
            raise DatasetProfileAddError("timestamp_nearest requires a LiDAR timestamp CSV")
        if manifest.camera.timestamp is None:
            raise DatasetProfileAddError(
                "timestamp_nearest requires the existing camera timestamp specification"
            )
        if lidar.tolerance_ns is None or lidar.tolerance_ns < 0:
            raise DatasetProfileAddError("timestamp_nearest requires non-negative tolerance")


def _synchronize_new_profile(
    request: DatasetProfileAddRequest,
    manifest: DatasetManifestV2,
    data_root: Path,
) -> SynchronizationResult:
    lidar = request.lidar
    lidar_samples = make_sensor_samples(
        lidar.sensor_id,
        (
            (sample.source_sample_id, sample.relative_path)
            for sample in lidar.candidate.samples
        ),
    )
    lidar_timestamp = (
        _read_timestamp_setup(data_root, lidar.timestamp)
        if lidar.timestamp is not None
        else None
    )
    camera_samples: tuple[SensorSample, ...] = ()
    camera_timestamp = None
    if lidar.sync_method != "lidar_only":
        assert request.camera is not None
        assert manifest.camera is not None
        camera_samples = make_sensor_samples(
            manifest.camera.id,
            (
                (sample.source_sample_id, sample.relative_path)
                for sample in request.camera.candidate.samples
            ),
        )
        if manifest.camera.timestamp is not None:
            spec = manifest.camera.timestamp
            camera_timestamp = read_timestamp_table(
                _data_path(data_root, spec.path),
                sample_id_column=spec.sample_id_column,
                value_column=spec.value_column,
                unit=spec.unit,  # type: ignore[arg-type]
                clock_domain=spec.clock_domain,
                offset_ns=spec.offset_ns,
            )
    return synchronize_profile(
        profile_id=lidar.profile_id,
        lidar_samples=lidar_samples,
        method=lidar.sync_method,
        camera_samples=camera_samples,
        lidar_timestamps=lidar_timestamp,
        camera_timestamps=(
            camera_timestamp if lidar.sync_method == "timestamp_nearest" else None
        ),
        tolerance_ns=lidar.tolerance_ns,
    )


def _source_paths(
    request: DatasetProfileAddRequest,
    manifest: DatasetManifestV2,
    adapters: tuple[DeviceCentricV2Adapter, ...],
    data_root: Path,
    config_root: Path,
) -> tuple[tuple[str, Path], ...]:
    paths: dict[str, Path] = {}
    for sample in request.lidar.candidate.samples:
        paths[f"new_lidar:{sample.relative_path}"] = _data_path(
            data_root, sample.relative_path
        )
    if request.lidar.timestamp is not None:
        relative = request.lidar.timestamp.relative_path
        paths[f"new_lidar_timestamp:{relative}"] = _data_path(data_root, relative)
    if request.camera is not None:
        for sample in request.camera.candidate.samples:
            paths[f"camera:{sample.relative_path}"] = _data_path(
                data_root, sample.relative_path
            )
        if manifest.camera is not None and manifest.camera.timestamp is not None:
            relative = manifest.camera.timestamp.path
            paths[f"camera_timestamp:{relative}"] = _data_path(data_root, relative)
    paths[f"taxonomy:{manifest.taxonomy.path}"] = _config_path(
        config_root, manifest.taxonomy.path
    )
    for adapter in adapters:
        relative = adapter.profile.frame_index.path
        paths[f"index:{adapter.profile.id}:{relative}"] = _config_path(
            config_root, relative
        )
    return tuple(sorted(paths.items()))


def _inventory_sha256(
    paths: tuple[tuple[str, Path], ...],
    *,
    progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> str:
    rows: list[tuple[str, str]] = []
    for position, (key, path) in enumerate(paths, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress("fingerprint", position, len(paths), key)
        rows.append((key, _sha256(path)))
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_existing_labels(
    adapters: tuple[DeviceCentricV2Adapter, ...],
) -> int:
    label_count = 0
    for adapter in adapters:
        repository = V2LabelRepository.for_sidecar(adapter)
        recovery = V2RecoveryStore(repository)
        for frame_id in adapter.index.frame_ids:
            if repository.exists(frame_id):
                repository.load(frame_id)
                label_count += 1
            recovery_result = recovery.inspect(frame_id)
            if recovery_result.error:
                raise DatasetProfileAddError(
                    f"invalid recovery snapshot for {adapter.profile.id}/{frame_id}: "
                    f"{recovery_result.error}"
                )
    return label_count


def _validate_representative_points(lidar: LidarSetup, data_root: Path) -> None:
    spec = PointCloudSpec(
        columns=lidar.point_columns,
        source_frame=lidar.coordinate_frame,
        dtype=lidar.point_dtype,
        byte_order=lidar.byte_order,
    )
    loader = PcdPointCloudLoader() if lidar.candidate.format == "pcd" else BinaryPointCloudLoader()
    count = len(lidar.candidate.samples)
    for index in sorted({0, count // 2, count - 1}):
        sample = lidar.candidate.samples[index]
        path = _data_path(data_root, sample.relative_path)
        try:
            cloud = loader.load(
                path,
                spec,
                sensor_id=lidar.sensor_id,
                return_id="1",
            )
        except (OSError, TypeError, ValueError) as exc:
            raise DatasetProfileAddError(
                f"cannot load representative LiDAR sample {path}: {exc}"
            ) from exc
        if cloud.point_count == 0:
            raise DatasetProfileAddError(
                f"representative LiDAR sample has no usable XYZ points: {path}"
            )


def _append_lidar_and_profile(
    document: dict[str, Any],
    request: DatasetProfileAddRequest,
    *,
    generation_name: str,
    index_name: str,
    index_payload: bytes,
    data_root: Path,
    camera_id: str | None,
) -> None:
    lidar = request.lidar
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
    if lidar.timestamp is not None:
        lidar_document["timestamp"] = _timestamp_document(data_root, lidar.timestamp)
    cast(list[dict[str, Any]], document["lidars"]).append(lidar_document)
    profile_camera = (
        {
            "camera_id": camera_id,
            "mode": "display_only",
            "calibration_path": None,
            "calibration_sha256": None,
        }
        if camera_id is not None
        else None
    )
    cast(list[dict[str, Any]], document["profiles"]).append(
        {
            "id": lidar.profile_id,
            "display_name": lidar.profile_display_name,
            "lidar_id": lidar.sensor_id,
            "camera": profile_camera,
            "frame_index": {
                "schema_version": "2.0",
                "path": f"generations/{generation_name}/sync/{index_name}",
                "sha256": hashlib.sha256(index_payload).hexdigest(),
                "frame_count": len(request.lidar.candidate.samples),
                "generation": {
                    "method": lidar.sync_method,
                    "tolerance_ns": lidar.tolerance_ns,
                },
            },
        }
    )


def _timestamp_document(root: Path, setup: TimestampSetup) -> dict[str, Any]:
    path = _data_path(root, setup.relative_path)
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


def _read_timestamp_setup(root: Path, setup: TimestampSetup) -> TimestampTable:
    return read_timestamp_table(
        _data_path(root, setup.relative_path),
        sample_id_column=setup.sample_id_column,
        value_column=setup.value_column,
        unit=setup.unit,
        clock_domain=setup.clock_domain,
        offset_ns=setup.offset_ns,
    )


def _data_path(root: Path, value: str) -> Path:
    return _safe_path(root, value, "data")


def _config_path(root: Path, value: str) -> Path:
    return _safe_path(root, value, "configuration")


def _safe_path(root: Path, value: str, label: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise DatasetProfileAddError(f"unsafe {label} path: {value}")
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetProfileAddError(f"{label} path escapes root: {value}") from exc
    if not path.is_file():
        raise DatasetProfileAddError(f"required {label} file is missing: {path}")
    return path


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    _write_bytes(path, payload)


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
    allowed = {config_root.resolve(), (config_root / "generations").resolve()}
    if path.parent.resolve() not in allowed or not path.name.startswith("."):
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
        raise DatasetProfileAddCancelled("dataset profile addition was cancelled")
