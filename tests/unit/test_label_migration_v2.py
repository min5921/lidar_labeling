from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.background_task import TaskCancelled, TaskControl
from lidar_label_tool.services.label_migration_v2 import (
    LabelMigrationError, LabelMigrationRequest, analyze_label_migration_v2,
    migrate_labels_v2, parse_class_mapping,
)
from lidar_label_tool.services.session_lock import SessionLock, SessionLockExistsError, SessionLockInfo
from tests.fixture_builders import create_v2_dataset


def _fixture(root: Path) -> LabelMigrationRequest:
    create_v2_dataset(root, frame_count=2)
    source = root / "annotations" / "lidar_label_tool"
    source.mkdir(parents=True)
    for frame_id in ("000000", "000001"):
        label = FrameLabel(
            dataset_id="ds_fixture_v2", frame_id=frame_id,
            point_cloud_paths={"aeva": (f"sensors/lidar/AEVA/frames/{frame_id}.bin",)},
            image_paths={}, reference_frame="lidar:AEVA", revision=3, frame_status="reviewed",
            objects=(LabeledObject("source-id", "Car", Box3D(1, 2, 3, 4, 2, 1.5, 0.1),
                                   source={"original_id": "a/b"}, extra_fields={"vendor": [1, 2]}),),
            extra_fields={"note": "원본 유지"},
            provenance={"source_format": "legacy", "source_paths": [], "source_fingerprints": {},
                        "vendor_metadata": {"flag": True}},
        )
        text = json.dumps(label.to_dict(), ensure_ascii=False)
        (source / f"{frame_id}.json").write_text(text, encoding="utf-8")
        (source / f"{frame_id}.json.bak").write_text("original backup bytes", encoding="utf-8")
    return LabelMigrationRequest(root, source, root, "aeva_profile", {"Car": "car"})


def test_reparse_point_is_rejected_without_python312_is_junction(tmp_path: Path) -> None:
    from lidar_label_tool.services.label_migration_v2 import _require_plain_path

    with patch.object(Path, "lstat", return_value=SimpleNamespace(st_file_attributes=0x400)):
        with patch.object(Path, "is_symlink", return_value=False):
            with pytest.raises(LabelMigrationError, match="junction"):
                _require_plain_path(tmp_path)


def test_noncanonical_uppercase_json_is_not_silently_omitted(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    source = request.source_annotation_dir / "000001.json"
    source.rename(source.with_suffix(".JSON"))
    with pytest.raises(LabelMigrationError, match="filename/frame_id"):
        analyze_label_migration_v2(request)


def test_uppercase_backup_is_fingerprinted_and_preserved(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    source = request.source_annotation_dir / "000001.json.bak"
    backup = source.with_name("000001.JSON.BAK")
    source.rename(backup)
    plan = analyze_label_migration_v2(request)
    assert "000001.JSON.BAK" in plan.inventory
    backup.write_bytes(b"externally changed backup")
    with pytest.raises(LabelMigrationError, match="변경"):
        migrate_labels_v2(plan, confirmed=True)


def test_input_paths_are_checked_before_resolve(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    with patch(
        "lidar_label_tool.services.label_migration_v2._require_plain_path",
        side_effect=LabelMigrationError("junction input"),
    ):
        with pytest.raises(LabelMigrationError, match="junction input"):
            analyze_label_migration_v2(request)


@pytest.mark.parametrize("lock_class", ["SessionLock", "V2SessionLock"])
def test_lock_cleanup_error_does_not_report_completed_migration_as_failed(tmp_path: Path, lock_class: str) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    with patch(
        f"lidar_label_tool.services.label_migration_v2.{lock_class}.release",
        side_effect=OSError("injected release failure"),
    ):
        result = migrate_labels_v2(plan, confirmed=True)
    assert result.status == "migrated"
    assert result.report_path.is_file()
    assert (result.target_namespace / "000000.json").is_file()
    assert result.warnings and "lock" in result.warnings[0]


def _edit_source(request: LabelMigrationRequest, change: object) -> None:
    path = request.source_annotation_dir / "000000.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert callable(change)
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_migration_is_previewed_atomic_preserves_source_unknowns_and_next_save(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in request.source_annotation_dir.iterdir()}
    plan = analyze_label_migration_v2(request)
    assert not plan.target_namespace.exists()
    with pytest.raises(LabelMigrationError, match="확인"):
        migrate_labels_v2(plan)
    result = migrate_labels_v2(plan, confirmed=True)
    assert result.status == "migrated"
    assert result.frame_count == 2 and result.object_count == 2
    assert result.report_path.is_file()
    for name, payload in before.items():
        assert (request.source_annotation_dir / name).read_bytes() == payload
    adapter = DeviceCentricV2Adapter(tmp_path)
    repository = V2LabelRepository.for_sidecar(adapter)
    label = repository.load("000000")
    assert label.revision == 4 and label.frame_status == "reviewed"
    assert label.objects[0].id == "source-id" and label.objects[0].class_name == "car"
    assert label.objects[0].extra_fields["vendor"] == [1, 2]
    assert label.objects[0].source == {"original_id": "a/b"}
    assert label.extra_fields["note"] == "원본 유지"
    assert label.provenance["vendor_metadata"] == {"flag": True}
    assert label.extra_fields["migration_source_context"]["revision"] == 3
    migration = label.provenance["migration"]
    saved = repository.save(label)
    assert saved.revision == 5
    assert repository.load("000000").provenance["migration"] == migration
    assert not (result.target_namespace / ".session.lock").exists()
    assert not (request.source_annotation_dir / ".session.lock").exists()


def test_migration_idempotence_requires_completed_report_and_unchanged_outputs(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    migrate_labels_v2(plan, confirmed=True)
    before = {path.name: path.read_bytes() for path in plan.target_namespace.iterdir()}
    repeated = analyze_label_migration_v2(request)
    assert repeated.already_migrated
    assert migrate_labels_v2(repeated, confirmed=True).status == "already_migrated"
    assert {path.name: path.read_bytes() for path in plan.target_namespace.iterdir()} == before
    (plan.target_namespace / "000000.json").write_text("external edit", encoding="utf-8")
    with pytest.raises(LabelMigrationError, match="이미 존재"):
        analyze_label_migration_v2(request)


@pytest.mark.parametrize("mutation", [
    lambda doc: doc.update(dataset_id="other"),
    lambda doc: doc.update(reference_frame="vehicle"),
    lambda doc: doc["point_cloud_paths"].update(other=["another.bin"]),
    lambda doc: doc["point_cloud_paths"].update(aeva=["sensors/lidar/AEVA/frames/000001.bin"]),
    lambda doc: doc["objects"][0].update(class_name="Unknown"),
    lambda doc: doc["objects"].append(doc["objects"][0]),
    lambda doc: doc.update(schema_version="2.0"),
    lambda doc: doc.update(frame_id="000001"),
    lambda doc: doc.update(point_cloud_path="different.bin"),
])
def test_ambiguous_identity_or_unmapped_classes_abort_all_frames(tmp_path: Path, mutation: object) -> None:
    request = _fixture(tmp_path)
    _edit_source(request, mutation)
    with pytest.raises((ValueError, KeyError)):
        analyze_label_migration_v2(request)
    assert not (request.source_annotation_dir / "aeva_profile").exists()


@pytest.mark.parametrize("changed", ["label", "backup", "point", "manifest", "inventory"])
def test_preview_fingerprint_rejects_external_changes(tmp_path: Path, changed: str) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    paths = {
        "label": request.source_annotation_dir / "000000.json",
        "backup": request.source_annotation_dir / "000000.json.bak",
        "point": tmp_path / "sensors/lidar/AEVA/frames/000000.bin",
        "manifest": tmp_path / "dataset.json",
        "inventory": request.source_annotation_dir / "999999.json",
    }
    path = paths[changed]
    path.write_bytes(path.read_bytes() + b" " if path.exists() else b"{}")
    with pytest.raises((ValueError, KeyError)):
        migrate_labels_v2(plan, confirmed=True)
    assert not plan.target_namespace.exists()


def test_staging_failure_is_all_or_nothing(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    with patch("lidar_label_tool.services.label_migration_v2._activate_namespace", side_effect=OSError("disk error")):
        with pytest.raises(OSError, match="disk error"):
            migrate_labels_v2(plan, confirmed=True)
    assert not plan.target_namespace.exists()
    assert not list(plan.target_namespace.parent.glob(".migration-*"))
    assert not (request.source_annotation_dir / ".session.lock").exists()


def test_cancel_during_staging_keeps_source_and_no_partial_targets(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    task = TaskControl(progress=lambda progress: task.cancel() if progress.stage == "migration-staging" else None)
    with pytest.raises(TaskCancelled):
        migrate_labels_v2(plan, confirmed=True, task=task)
    assert not plan.target_namespace.exists()
    assert not list(plan.target_namespace.parent.glob(".migration-*"))


def test_existing_empty_namespace_and_active_source_lock_are_not_replaced(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    lock = SessionLock(request.source_annotation_dir)
    lock.acquire(SessionLockInfo.current(dataset_id=plan.source_dataset_id, dataset_root=tmp_path, workspace_root=None))
    try:
        with pytest.raises(SessionLockExistsError):
            migrate_labels_v2(plan, confirmed=True)
        assert lock.path.is_file()
    finally:
        lock.release()
    plan.target_namespace.mkdir(parents=True)
    with pytest.raises(LabelMigrationError, match="이미 존재"):
        analyze_label_migration_v2(request)
    assert plan.target_namespace.is_dir()


def test_new_namespace_race_does_not_overwrite_other_writer(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    def progress(event: object) -> None:
        if getattr(event, "stage") == "migration-staging" and not plan.target_namespace.exists():
            plan.target_namespace.mkdir()
            (plan.target_namespace / "keep.txt").write_text("other writer", encoding="utf-8")
    with pytest.raises(OSError):
        migrate_labels_v2(plan, confirmed=True, task=TaskControl(progress=progress))
    assert (plan.target_namespace / "keep.txt").read_text(encoding="utf-8") == "other writer"
    assert not (plan.target_namespace / "000000.json").exists()


def test_legacy_dataset_id_requires_manifest_binding_and_explicit_confirmation(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    for path in request.source_annotation_dir.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        document["dataset_id"] = "한글 legacy ID"
        path.write_text(json.dumps(document), encoding="utf-8")
    request = replace(request, legacy_dataset_id="한글 legacy ID")
    with pytest.raises(LabelMigrationError, match="binding"):
        analyze_label_migration_v2(request)
    manifest_path = tmp_path / "dataset.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["metadata"] = {"legacy_dataset_id": "한글 legacy ID"}
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    plan = analyze_label_migration_v2(request)
    migrate_labels_v2(plan, confirmed=True)
    label = V2LabelRepository.for_sidecar(DeviceCentricV2Adapter(tmp_path)).load("000000")
    assert label.dataset_id == "ds_fixture_v2"
    assert label.provenance["migration"]["legacy_dataset_id"] == "한글 legacy ID"


def test_mapping_syntax_rejects_duplicates_and_missing_values() -> None:
    assert parse_class_mapping("Car = car\n\nPerson = pedestrian") == {"Car": "car", "Person": "pedestrian"}
    for text in ("Car", "Car=", "=car", "Car=car\nCar=car"):
        with pytest.raises(LabelMigrationError):
            parse_class_mapping(text)


def test_source_mutation_during_staging_aborts_before_activation(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    plan = analyze_label_migration_v2(request)
    path = request.source_annotation_dir / "000000.json"
    def progress(event: object) -> None:
        if getattr(event, "stage") == "migration-staging":
            path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(LabelMigrationError, match="변경"):
        migrate_labels_v2(plan, confirmed=True, task=TaskControl(progress=progress))
    assert not plan.target_namespace.exists()
    assert path.read_bytes().endswith(b" ")


def test_corrupt_bin_is_not_migrated(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    (tmp_path / "sensors/lidar/AEVA/frames/000000.bin").write_bytes(b"broken")
    with pytest.raises(ValueError):
        analyze_label_migration_v2(request)


def test_workspace_migration_uses_exact_profile_lidar_namespace(tmp_path: Path) -> None:
    request = _fixture(tmp_path / "한글 원본")
    request = replace(request, workspace_root=tmp_path / "외부 작업")
    plan = analyze_label_migration_v2(request)
    result = migrate_labels_v2(plan, confirmed=True)
    assert result.target_namespace == (
        tmp_path / "외부 작업/ds_fixture_v2/annotations/lidar_label_tool/aeva_profile/aeva"
    )
    assert not (request.config_root / "annotations/lidar_label_tool/aeva_profile").exists()


def test_safe_legacy_dataset_id_cannot_be_renamed_even_with_metadata_binding(tmp_path: Path) -> None:
    request = _fixture(tmp_path)
    path = tmp_path / "dataset.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["dataset_id"] = "ds_renamed"
    document["metadata"] = {"legacy_dataset_id": "ds_fixture_v2"}
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(LabelMigrationError, match="그대로"):
        analyze_label_migration_v2(replace(request, legacy_dataset_id="ds_fixture_v2"))
