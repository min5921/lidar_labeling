from dataclasses import replace
import json
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.object_source import SavedLabelObjectLoader
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.box_propagation import created_objects, merge_carried_objects
from lidar_label_tool.services.object_transfer import apply_object_transfer, plan_object_transfer
from lidar_label_tool.ui.object_transfer_dialog import ObjectTransferDialog
from tests.fixture_builders import create_v2_dataset


def _object(object_id, x=1):
    return LabeledObject(
        object_id, "car", Box3D(x, 2, 1, 4, 2, 1.6, 0.25),
        attributes={"name": "차량"}, source={"raw": {"id": object_id}},
        extra_fields={"vendor": {"keep": True}},
    )


def _label(frame_id, *objects):
    return FrameLabel(
        dataset_id="chunk_a", frame_id=frame_id, reference_frame="lidar:AEVA",
        point_cloud_paths={"aeva": (f"points/{frame_id}.bin",)}, image_paths={},
        objects=objects, revision=1,
    )


def _saved_source(tmp_path, *objects):
    path = tmp_path / "이전 폴더 마지막 000999.json"
    path.write_text(json.dumps(_label("000999", *objects).to_dict()), encoding="utf-8")
    return SavedLabelObjectLoader().load(path)


def test_bulk_transfer_preserves_target_identity_ids_metadata_and_existing_boxes(tmp_path):
    source = _saved_source(tmp_path, _object("a"), _object("b"))
    kept = _object("a", x=50)
    target = replace(_label("000000", kept), dataset_id="chunk_b", revision=7)
    before = source.path.read_bytes()
    plan = plan_object_transfer(source, target, allowed_classes=["car"])
    copied = apply_object_transfer(plan, target)

    assert plan.skipped_ids == ("a",)
    assert copied.objects[0] == kept
    assert [obj.id for obj in copied.objects] == ["a", "b"]
    assert copied.objects[1].box3d == source.objects[1].box3d
    assert copied.objects[1].source == source.objects[1].source
    assert copied.objects[1].attributes == source.objects[1].attributes
    assert copied.objects[1].extra_fields["vendor"] == {"keep": True}
    record = copied.objects[1].extra_fields["object_transfer_history"][0]
    assert record["source_dataset_id"] == "chunk_a"
    assert record["source_label_sha256"] == source.sha256
    assert copied.dataset_id == "chunk_b"
    assert copied.frame_id == "000000"
    assert copied.point_cloud_paths == target.point_cloud_paths
    assert copied.revision == 7
    assert copied.frame_status == "in_progress"
    assert source.path.read_bytes() == before
    assert target.objects == (kept,)

    repeat = plan_object_transfer(source, copied, allowed_classes=["car"])
    assert apply_object_transfer(repeat, copied) is copied


def test_transferred_imported_objects_continue_to_next_frame_and_undo_as_one_edit(tmp_path):
    source = _saved_source(tmp_path, _object("a"), _object("b"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    transferred = apply_object_transfer(
        plan_object_transfer(source, target, allowed_classes=["car"]), target,
    )
    history = AnnotationHistory.start(target)
    history.apply(transferred)
    assert history.undo() == target
    assert history.redo() == transferred
    assert created_objects(source.objects) == ()
    carried = created_objects(transferred.objects)
    next_label, ids = merge_carried_objects(replace(target, frame_id="000001"), carried)
    assert ids == ("a", "b")
    assert [obj.id for obj in next_label.objects] == ["a", "b"]


@pytest.mark.parametrize("mismatch", ["lidar", "reference", "coordinates", "class"])
def test_incompatible_transfer_is_rejected_without_partial_edits(tmp_path, mismatch):
    source = _saved_source(tmp_path, _object("a"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    classes = ["car"]
    if mismatch == "lidar":
        target = replace(target, point_cloud_paths={"other": ("points.bin",)})
    elif mismatch == "reference":
        target = replace(target, reference_frame="other")
    elif mismatch == "coordinates":
        target = replace(target, coordinate_system={"x": "forward", "y": "right", "z": "up"})
    else:
        classes = ["pedestrian"]
    with pytest.raises(ValueError):
        plan_object_transfer(source, target, allowed_classes=classes)
    assert target.objects == ()


def test_object_subset_is_explicit_and_unknown_id_is_rejected(tmp_path):
    source = _saved_source(tmp_path, _object("a"), replace(_object("b"), class_name="unknown"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    plan = plan_object_transfer(source, target, allowed_classes=["car"], selected_ids=["a"])
    assert [obj.id for obj in apply_object_transfer(plan, target).objects] == ["a"]
    with pytest.raises(ValueError, match="없는 객체"):
        plan_object_transfer(source, target, allowed_classes=["car"], selected_ids=["missing"])
    empty = plan_object_transfer(source, target, allowed_classes=["car"], selected_ids=[])
    assert apply_object_transfer(empty, target) is target


def test_source_or_target_changed_after_preview_cannot_be_applied(tmp_path):
    source = _saved_source(tmp_path, _object("a"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    plan = plan_object_transfer(source, target, allowed_classes=["car"])
    with pytest.raises(ValueError, match="현재 프레임"):
        apply_object_transfer(plan, replace(target, frame_status="reviewed"))
    source.path.write_bytes(source.path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="이전 작업 라벨"):
        apply_object_transfer(plan, target)
    assert target.objects == ()


def test_missing_source_file_cannot_apply_an_old_preview(tmp_path):
    source = _saved_source(tmp_path, _object("a"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    plan = plan_object_transfer(source, target, allowed_classes=["car"])
    source.path.unlink()
    with pytest.raises(OSError):
        apply_object_transfer(plan, target)
    assert target.objects == ()


def test_transfer_preserves_history_and_rejects_malformed_history(tmp_path):
    old_history = [{"operation": "dataset_transfer", "vendor": {"keep": True}}]
    obj = replace(_object("a"), extra_fields={"object_transfer_history": old_history})
    source = _saved_source(tmp_path, obj)
    target = replace(_label("000000"), dataset_id="chunk_b")
    copied = apply_object_transfer(
        plan_object_transfer(source, target, allowed_classes=["car"]), target,
    )
    history = copied.objects[0].extra_fields["object_transfer_history"]
    assert history[:-1] == old_history
    assert len(history) == 2
    assert source.objects[0].extra_fields["object_transfer_history"] == old_history
    assert source.objects[0].extra_fields["object_transfer_history"] is not history

    malformed = replace(obj, extra_fields={"object_transfer_history": "must not overwrite"})
    source = _saved_source(tmp_path, malformed)
    with pytest.raises(ValueError, match="이력 형식"):
        plan_object_transfer(source, target, allowed_classes=["car"])
    assert target.objects == ()


@pytest.mark.parametrize("bad_input", ["json", "version", "duplicate_id", "nan", "metadata"])
def test_loader_rejects_corrupt_or_unsupported_saved_labels(tmp_path, bad_input):
    document = _label("000999", _object("a")).to_dict()
    if bad_input == "version":
        document["schema_version"] = {}
    elif bad_input == "duplicate_id":
        document["objects"].append(document["objects"][0])
    elif bad_input == "nan":
        document["objects"][0]["box3d"]["z"] = float("nan")
    elif bad_input == "metadata":
        document["objects"][0]["source"] = 42
    path = tmp_path / "bad.json"
    path.write_text("{" if bad_input == "json" else json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        SavedLabelObjectLoader().load(path)


def test_v2_transfer_between_two_folders_saves_with_destination_identity(tmp_path):
    repositories = []
    labels = []
    for name in ("chunk_a", "chunk_b"):
        root = tmp_path / name
        root.mkdir()
        manifest = create_v2_dataset(root)
        manifest["dataset_id"] = name
        (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
        adapter = DeviceCentricV2Adapter(root)
        repositories.append(V2LabelRepository.for_sidecar(adapter))
        source = adapter.load_source_frame("000001" if name == "chunk_a" else "000000")
        labels.append(WaymoLabelImporter({}).import_laser_labels(source))
    source_repo, target_repo = repositories
    source_repo.save(replace(labels[0], objects=(_object("a"), _object("b"))))
    source_path = source_repo.path_for("000001")
    original = source_path.read_bytes()
    source = SavedLabelObjectLoader().load(source_path)
    assert source.schema_version == "2.0"
    assert source.profile_id == "aeva_profile"
    target_repo.save(apply_object_transfer(
        plan_object_transfer(source, labels[1], allowed_classes=["car"]), labels[1],
    ))
    loaded = target_repo.load("000000")
    document = json.loads(target_repo.path_for("000000").read_text(encoding="utf-8"))
    assert loaded.dataset_id == "chunk_b"
    assert [obj.id for obj in loaded.objects] == ["a", "b"]
    assert document["profile_id"] == "aeva_profile"
    assert document["point_cloud_path"].endswith("000000.bin")
    assert document["frame_id"] == "000000"
    assert loaded.objects[0].extra_fields["object_transfer_history"][0]["source_dataset_id"] == "chunk_a"
    assert source_path.read_bytes() == original


def test_failed_transfer_save_preserves_previous_source_and_target_json(tmp_path):
    source = _saved_source(tmp_path, _object("imported"))
    original_source = source.path.read_bytes()
    root = tmp_path / "다음 폴더"
    root.mkdir()
    create_v2_dataset(root)
    adapter = DeviceCentricV2Adapter(root)
    repository = V2LabelRepository.for_sidecar(adapter)
    label = WaymoLabelImporter({}).import_laser_labels(adapter.load_source_frame("000000"))
    target = repository.save(replace(label, objects=(_object("existing"),)))
    path = repository.path_for("000000")
    original_target = path.read_bytes()
    copied = apply_object_transfer(
        plan_object_transfer(source, target, allowed_classes=["car"]), target,
    )
    with (
        patch("lidar_label_tool.io.labels.v2_repository.os.replace", side_effect=OSError("disk failure")),
        pytest.raises(OSError, match="disk failure"),
    ):
        repository.save(copied)
    assert path.read_bytes() == original_target
    assert source.path.read_bytes() == original_source
    assert not list(path.parent.glob("*.tmp"))


def test_dialog_previews_selection_and_prevents_unknown_class_import(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = _saved_source(tmp_path, _object("a"), replace(_object("b"), class_name="unknown"))
    target = replace(_label("000000"), dataset_id="chunk_b")
    dialog = ObjectTransferDialog(source, target, ["car"])
    assert not dialog.import_button.isEnabled()
    assert "없는 클래스" in dialog.status_label.text()
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.import_button.isEnabled()
    assert [obj.id for obj in dialog.plan.additions] == ["a"]
    dialog.reject()
    assert target.objects == ()
    app.processEvents()


def test_dialog_with_empty_or_duplicate_only_sources_has_no_import_action(tmp_path):
    app = QApplication.instance() or QApplication([])
    target = replace(_label("000000", _object("a")), dataset_id="chunk_b")
    for objects in ((), (_object("a"),)):
        source = _saved_source(tmp_path, *objects)
        dialog = ObjectTransferDialog(source, target, ["car"])
        assert not dialog.import_button.isEnabled()
        dialog.reject()
    app.processEvents()
