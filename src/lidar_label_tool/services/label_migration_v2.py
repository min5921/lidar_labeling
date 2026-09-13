"""Explicit, all-or-nothing migration of a saved v1 working-label namespace.

This service never transforms coordinates, guesses class mappings or changes source
labels. A complete new namespace (including its report) is activated by one atomic,
no-replace directory rename. Existing target namespaces are never merged.
"""
from __future__ import annotations

import ctypes
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from typing import Any, Mapping
from uuid import uuid4

from lidar_label_tool import __version__
from lidar_label_tool.domain.labels import FrameLabel, utc_now_iso
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.json_schema import validate_json_document
from lidar_label_tool.io.labels.object_source import normalized_label_coordinates
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.background_task import TaskControl
from lidar_label_tool.services.session_lock import SessionLock, SessionLockInfo
from lidar_label_tool.services.session_lock_v2 import V2SessionLock, V2SessionLockInfo


REPORT_NAME = ".migration-report.json"
_MISSING = "missing"
_MACHINE_ID = re.compile(
    r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))"
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$"
)


class LabelMigrationError(ValueError):
    """A migration cannot prove identity or cannot preserve an existing artifact."""


@dataclass(frozen=True, slots=True)
class LabelMigrationRequest:
    config_root: Path
    source_annotation_dir: Path
    source_data_root: Path
    profile_id: str
    class_mapping: Mapping[str, str]
    workspace_root: Path | None = None
    legacy_dataset_id: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationFrame:
    frame_id: str
    source_name: str
    source_sha256: str
    source_revision: int
    object_count: int
    document_json: str


@dataclass(frozen=True, slots=True)
class LabelMigrationPlan:
    request: LabelMigrationRequest
    target_namespace: Path
    dataset_id: str
    profile_id: str
    label_lidar_id: str
    source_dataset_id: str
    frames: tuple[MigrationFrame, ...]
    fingerprints: tuple[tuple[str, str], ...]
    inventory: tuple[str, ...]
    plan_sha256: str
    already_migrated: bool = False

    @property
    def object_count(self) -> int:
        return sum(frame.object_count for frame in self.frames)


@dataclass(frozen=True, slots=True)
class LabelMigrationResult:
    status: str
    target_namespace: Path
    report_path: Path
    frame_count: int
    object_count: int
    warnings: tuple[str, ...] = ()


def parse_class_mapping(text: str) -> dict[str, str]:
    """Parse explicit ``source class = target class_id`` lines; never infer aliases."""
    result: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        source, separator, target = line.partition("=")
        source, target = source.strip(), target.strip()
        if not separator or not source or not target or source in result:
            raise LabelMigrationError(f"class mapping {number}행이 잘못되었거나 중복입니다.")
        result[source] = target
    return result


def analyze_label_migration_v2(
    request: LabelMigrationRequest, *, task: TaskControl | None = None,
) -> LabelMigrationPlan:
    """Read and validate every source frame without creating any output files."""
    task = task or TaskControl()
    task.check_cancelled()
    for directory in (
        request.config_root, request.source_annotation_dir, request.source_data_root,
        request.workspace_root,
    ):
        if directory is not None:
            _require_plain_path(Path(directory))
    request = replace(
        request, config_root=Path(request.config_root).resolve(),
        source_annotation_dir=Path(request.source_annotation_dir).resolve(),
        source_data_root=Path(request.source_data_root).resolve(),
        workspace_root=(Path(request.workspace_root).resolve() if request.workspace_root else None),
        class_mapping=dict(request.class_mapping),
    )
    if not request.source_annotation_dir.is_dir() or not request.source_data_root.is_dir():
        raise LabelMigrationError("v1 작업 라벨 폴더와 원본 데이터 루트를 확인하세요.")
    manifest_before = _sha256(request.config_root / "dataset.json", task)
    adapter = DeviceCentricV2Adapter(request.config_root, request.profile_id)
    repository = _repository(request, adapter)
    target = repository.annotation_dir
    # Do not follow a redirected output namespace or any redirected parent.
    _require_plain_path(target)
    if target == request.source_annotation_dir or target in request.source_annotation_dir.parents:
        raise LabelMigrationError("대상 namespace 안의 폴더를 v1 원본으로 사용할 수 없습니다.")
    class_ids = {item.id for item in adapter.taxonomy.classes}
    if any(not isinstance(key, str) or not key or value not in class_ids
           for key, value in request.class_mapping.items()):
        raise LabelMigrationError("class mapping의 대상 class_id가 대상 taxonomy에 없습니다.")
    inventory = _inventory(request.source_annotation_dir)
    names = tuple(name for name in inventory if name.casefold().endswith(".json"))
    if not names:
        raise LabelMigrationError("선택한 폴더에 저장된 v1 작업 라벨 JSON이 없습니다.")
    fingerprints: dict[str, str] = {}
    for relative in ("dataset.json", adapter.profile.frame_index.path, adapter.manifest.taxonomy.path):
        path = _safe_path(request.config_root, relative)
        fingerprints[str(path)] = _sha256(path, task)
    if fingerprints[str(request.config_root / "dataset.json")] != manifest_before:
        raise LabelMigrationError("분석 중 dataset.json이 변경되었습니다.")
    for name in inventory:
        path = _safe_path(request.source_annotation_dir, name)
        fingerprints[str(path)] = _sha256(path, task)
    migrated_at = utc_now_iso()
    mapping_hash = _document_hash(dict(request.class_mapping))
    frames: list[MigrationFrame] = []
    source_dataset_id: str | None = None
    for position, name in enumerate(names, 1):
        task.report("migration-analysis", position - 1, len(names), name)
        task.check_cancelled()
        path = _safe_path(request.source_annotation_dir, name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != fingerprints[str(path)]:
            raise LabelMigrationError(f"분석 중 원본 라벨이 변경되었습니다: {name}")
        document = json.loads(raw.decode("utf-8-sig"))
        validate_json_document(document, "label.schema.json")
        label = FrameLabel.from_dict(document)
        if name != f"{label.frame_id}.json":
            raise LabelMigrationError(f"라벨 filename/frame_id가 다릅니다: {name}")
        if source_dataset_id is not None and label.dataset_id != source_dataset_id:
            raise LabelMigrationError("한 source namespace에 여러 dataset_id가 있습니다.")
        source_dataset_id = label.dataset_id
        _require_dataset_binding(label.dataset_id, request, adapter)
        if label.reference_frame != repository.reference_frame:
            raise LabelMigrationError(f"reference frame이 달라 좌표 변환이 필요합니다: {name}")
        normalized_label_coordinates(label.coordinate_system)
        record = adapter.frame_record(label.frame_id)
        expected_paths = {repository.label_lidar_id: (record.lidar.path,)}
        if dict(label.point_cloud_paths) != expected_paths:
            raise LabelMigrationError(f"단일 LiDAR ID/point binding을 증명할 수 없습니다: {name}")
        if document.get("point_cloud_path", record.lidar.path) != record.lidar.path:
            raise LabelMigrationError(f"v1 단수/복수 point 경로가 충돌합니다: {name}")
        for root in (request.source_data_root, adapter.data_root):
            point = _safe_path(root, record.lidar.path)
            _capture(fingerprints, point, task)
        source_point = _safe_path(request.source_data_root, record.lidar.path)
        target_point = _safe_path(adapter.data_root, record.lidar.path)
        if fingerprints[str(source_point)] != fingerprints[str(target_point)]:
            raise LabelMigrationError(f"source/target point 파일 내용이 다릅니다: {name}")
        # Decode one cloud at a time in the worker. Corrupt BIN/PCD must not become
        # an apparently valid migrated annotation; no render/downsample is used.
        adapter.load_cloud_from_source(adapter.load_source_frame(label.frame_id), repository.label_lidar_id)
        missing = sorted({obj.class_name for obj in label.objects} - request.class_mapping.keys())
        if missing:
            raise LabelMigrationError(f"명시적인 class mapping이 필요합니다: {', '.join(missing)}")
        if any(not isinstance(item.get("source", {}), dict) for item in document["objects"]):
            raise LabelMigrationError(f"객체 source metadata는 JSON object여야 합니다: {name}")
        label = replace(
            label, dataset_id=repository.dataset_id,
            objects=tuple(replace(obj, class_name=request.class_mapping[obj.class_name])
                          for obj in label.objects),
        )
        converted = repository.document_for(label, revision=label.revision + 1, saved_at_utc=migrated_at)
        # Preserve original frame context explicitly when v2 replaces its meaning.
        if "migration_source_context" in document:
            raise LabelMigrationError(f"예약된 migration_source_context 확장 필드 충돌: {name}")
        converted["migration_source_context"] = {
            key: deepcopy(value) for key, value in document.items() if key != "objects"
        }
        for old, new in zip(document["objects"], converted["objects"]):
            if "class_id" in old:
                raise LabelMigrationError(f"v1 객체에 v2 class_id 필드가 이미 있어 모호합니다: {name}")
            new["class_name"] = old["class_name"]
        converted["provenance"]["migration"] = {
            "from_schema_version": "1.0", "source_path": name,
            "source_sha256": fingerprints[str(path)], "source_revision": label.revision,
            "migrated_at_utc": migrated_at, "tool_version": __version__,
            "class_mapping_sha256": mapping_hash,
            **({"legacy_dataset_id": label_id} if (label_id := request.legacy_dataset_id) else {}),
        }
        validate_json_document(converted, "label-v2.schema.json")
        repository.frame_label_from_document(converted)
        for optional_path in (record.camera.path if record.camera else None,
                              adapter.profile.camera.calibration_path if adapter.profile.camera else None):
            if optional_path:
                root = adapter.data_root if record.camera and optional_path == record.camera.path else request.config_root
                candidate = _safe_path(root, optional_path)
                _capture(fingerprints, candidate, task, optional=True)
        frames.append(MigrationFrame(label.frame_id, name, fingerprints[str(path)],
                                     label.revision, len(label.objects), _json_text(converted)))
    assert source_dataset_id is not None
    plan_hash = _document_hash({
        "dataset_id": repository.dataset_id, "profile_id": repository.profile_id,
        "label_lidar_id": repository.label_lidar_id, "source_dataset_id": source_dataset_id,
        "source_annotation_dir": str(request.source_annotation_dir),
        "source_data_root": str(request.source_data_root), "target_namespace": str(target),
        "class_mapping": dict(request.class_mapping), "fingerprints": fingerprints,
        "inventory": inventory,
    })
    plan = LabelMigrationPlan(request, target, repository.dataset_id, repository.profile_id,
                              repository.label_lidar_id, source_dataset_id, tuple(frames),
                              tuple(sorted(fingerprints.items())), inventory, plan_hash)
    if target.exists():
        if not _is_completed(plan, repository, task):
            raise LabelMigrationError("대상 namespace가 이미 존재합니다. 기존 라벨/복구/lock을 보존하고 이관을 중단합니다.")
        plan = replace(plan, already_migrated=True)
    _require_unchanged(plan, task)
    task.report("migration-analysis", len(names), len(names), "전체 frame 검증 완료")
    return plan


def migrate_labels_v2(
    plan: LabelMigrationPlan, *, confirmed: bool = False, task: TaskControl | None = None,
) -> LabelMigrationResult:
    """Activate a previewed plan only after explicit confirmation, without overwrite."""
    if not confirmed:
        raise LabelMigrationError("전체 frame 미리보기와 명시적인 사용자 확인이 필요합니다.")
    task = task or TaskControl()
    task.check_cancelled()
    current = analyze_label_migration_v2(plan.request, task=task)
    if current.plan_sha256 != plan.plan_sha256:
        raise LabelMigrationError("미리보기 이후 입력/설정이 변경되었습니다. 다시 분석하세요.")
    if current.already_migrated:
        return _result(plan, "already_migrated")
    source_lock = SessionLock(plan.request.source_annotation_dir)
    source_info = SessionLockInfo.current(dataset_id=plan.source_dataset_id,
                                         dataset_root=plan.request.source_data_root, workspace_root=None)
    source_lock.acquire(source_info)
    staging: Path | None = None
    staged_lock: V2SessionLock | None = None
    activated = False
    cleanup_warnings: list[str] = []
    try:
        _require_unchanged(plan, task)
        _require_plain_path(plan.target_namespace)
        if plan.target_namespace.exists():
            raise LabelMigrationError("분석 이후 대상 namespace가 생겼습니다.")
        parent = plan.target_namespace.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / f".migration-{uuid4().hex}"
        staging.mkdir()
        adapter = DeviceCentricV2Adapter(plan.request.config_root, plan.profile_id)
        staged_repository = V2LabelRepository(staging, adapter)
        staged_lock = V2SessionLock(staged_repository)
        staged_lock.acquire(V2SessionLockInfo.current(staged_repository))
        output_hashes: dict[str, str] = {}
        for position, frame in enumerate(plan.frames, 1):
            task.check_cancelled()
            document = json.loads(frame.document_json)
            validate_json_document(document, "label-v2.schema.json")
            staged_repository.frame_label_from_document(document)
            path = staged_repository.path_for(frame.frame_id)
            _write_exclusive(path, document)
            staged_repository.load(frame.frame_id)
            output_hashes[path.name] = _sha256(path, task)
            task.report("migration-staging", position, len(plan.frames), frame.frame_id)
        report = {
            "schema_version": "1.0", "kind": "v1_to_v2_label_migration", "status": "completed",
            "plan_sha256": plan.plan_sha256, "dataset_id": plan.dataset_id,
            "profile_id": plan.profile_id, "label_lidar_id": plan.label_lidar_id,
            "legacy_dataset_id": plan.source_dataset_id,
            "source_annotation_dir": str(plan.request.source_annotation_dir),
            "class_mapping": dict(plan.request.class_mapping), "tool_version": __version__,
            "completed_at_utc": utc_now_iso(), "frame_count": len(plan.frames),
            "object_count": plan.object_count, "output_sha256": output_hashes,
            "sources": {frame.source_name: frame.source_sha256 for frame in plan.frames},
            "fingerprints": dict(plan.fingerprints),
            "warnings": ["v1 recovery는 이관하지 않았습니다. 원본 v1 JSON과 .bak은 그대로 보존됩니다.",
                         "카메라/보정 context는 대상 profile 기준입니다. projection을 다시 검토하세요."],
        }
        _write_exclusive(staging / REPORT_NAME, report)
        _require_unchanged(plan, task)
        task.check_cancelled()
        _require_plain_path(plan.target_namespace)
        inspection = source_lock.inspect()
        if inspection.info is None or inspection.info.lock_id != source_info.lock_id:
            raise LabelMigrationError("원본 세션 lock 소유권이 변경되어 이관을 중단합니다.")
        if os.name != "nt":
            descriptor = os.open(staging, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # From this point cancellation cannot interrupt a completed atomic commit.
        _activate_namespace(staging, plan.target_namespace)
        activated = True
        staged_lock.path = plan.target_namespace / ".session.lock"
    finally:
        try:
            try:
                if staged_lock is not None:
                    _release_migration_lock(staged_lock, activated, cleanup_warnings)
            finally:
                if staging is not None and not activated and staging.exists():
                    # Only this call's unique, explicitly created staging namespace is removed.
                    _require_plain_path(staging)
                    shutil.rmtree(staging)
        finally:
            _release_migration_lock(source_lock, activated, cleanup_warnings)
    return replace(_result(plan, "migrated"), warnings=tuple(cleanup_warnings))


def _release_migration_lock(
    lock: SessionLock | V2SessionLock, activated: bool, warnings: list[str],
) -> None:
    try:
        released = lock.release()
    except OSError as exc:
        if not activated:
            raise
        logging.getLogger(__name__).exception("Migration committed but lock cleanup failed: %s", lock.path)
        warnings.append(f"이관은 완료됐지만 lock 해제에 실패했습니다: {lock.path} ({exc}). "
                        "완료 report를 확인하고 잔여 lock을 검토하세요.")
    else:
        if not released and activated:
            warnings.append(f"이관은 완료됐지만 lock 소유권이 달라 제거하지 않았습니다: {lock.path}. "
                            "다른 세션을 확인하세요.")


def _repository(request: LabelMigrationRequest, adapter: DeviceCentricV2Adapter) -> V2LabelRepository:
    if request.workspace_root is not None:
        return V2LabelRepository.for_workspace(request.workspace_root, adapter)
    return V2LabelRepository.for_sidecar(adapter)


def _require_dataset_binding(
    source_id: str, request: LabelMigrationRequest, adapter: DeviceCentricV2Adapter,
) -> None:
    if source_id == adapter.manifest.dataset_id:
        if request.legacy_dataset_id not in (None, source_id):
            raise LabelMigrationError("명시한 legacy_dataset_id가 원본과 다릅니다.")
        return
    if _MACHINE_ID.fullmatch(source_id):
        raise LabelMigrationError("안전한 v1 dataset_id는 변경하지 않고 대상 v2에서도 그대로 사용해야 합니다.")
    if request.legacy_dataset_id != source_id or adapter.manifest.metadata.get("legacy_dataset_id") != source_id:
        raise LabelMigrationError("dataset_id가 다릅니다. 명시적 legacy_dataset_id와 manifest metadata의 동일 binding이 모두 필요합니다.")


def _inventory(directory: Path) -> tuple[str, ...]:
    names = sorted(path.name for path in directory.iterdir()
                   if path.name.casefold().endswith((".json", ".json.bak")))
    if len({name.casefold() for name in names}) != len(names):
        raise LabelMigrationError("대소문자만 다른 원본 라벨 파일이 있습니다.")
    return tuple(names)


def _require_unchanged(plan: LabelMigrationPlan, task: TaskControl) -> None:
    if _inventory(plan.request.source_annotation_dir) != plan.inventory:
        raise LabelMigrationError("미리보기 이후 원본 라벨 목록이 변경되었습니다.")
    for path, expected in plan.fingerprints:
        task.check_cancelled()
        candidate = Path(path)
        _require_plain_path(candidate)
        actual = _sha256(candidate, task) if candidate.is_file() else _MISSING
        if actual != expected:
            raise LabelMigrationError(f"미리보기 이후 파일이 변경되었습니다: {path}")


def _capture(fingerprints: dict[str, str], path: Path, task: TaskControl, *, optional: bool = False) -> None:
    actual = _MISSING if optional and not path.is_file() else _sha256(path, task)
    previous = fingerprints.setdefault(str(path), actual)
    if previous != actual:
        raise LabelMigrationError(f"분석 중 파일이 변경되었습니다: {path}")


def _is_completed(plan: LabelMigrationPlan, repository: V2LabelRepository, task: TaskControl) -> bool:
    report_path = plan.target_namespace / REPORT_NAME
    if not report_path.is_file() or report_path.is_symlink():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "completed" or report.get("plan_sha256") != plan.plan_sha256:
            return False
        expected = report["output_sha256"]
        if set(expected) != {f"{frame.frame_id}.json" for frame in plan.frames}:
            return False
        for frame in plan.frames:
            path = repository.path_for(frame.frame_id)
            _require_plain_path(path)
            if _sha256(path, task) != expected[path.name]:
                return False
            repository.load(frame.frame_id)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
        raise LabelMigrationError(f"안전하지 않은 상대 경로: {relative}")
    candidate = root.joinpath(*pure.parts)
    _require_plain_path(candidate)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise LabelMigrationError(f"루트 밖 경로: {relative}")
    return candidate


def _require_plain_path(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            attributes = getattr(part.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        # Path.is_junction only exists in Python 3.12+. Reject reparse points on
        # every supported Windows Python, before resolving away their identity.
        if part.is_symlink() or attributes & 0x400:
            raise LabelMigrationError(f"이관 경로의 symlink/junction은 지원하지 않습니다: {part}")


def _sha256(path: Path, task: TaskControl) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            task.check_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(document: Mapping[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _document_hash(document: Mapping[str, Any]) -> str:
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_exclusive(path: Path, document: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(_json_text(document))
        stream.flush()
        os.fsync(stream.fileno())


def _activate_namespace(source: Path, target: Path) -> None:
    if os.name == "nt":
        # Windows rename never replaces an existing directory.
        os.rename(source, target)
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise LabelMigrationError("이 Linux는 atomic no-replace renameat2를 지원하지 않습니다.")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
    else:
        raise LabelMigrationError("전체 namespace 이관은 Windows 또는 renameat2 지원 Linux에서 실행하세요.")


def _result(plan: LabelMigrationPlan, status: str) -> LabelMigrationResult:
    return LabelMigrationResult(status, plan.target_namespace, plan.target_namespace / REPORT_NAME,
                                len(plan.frames), plan.object_count)
