from dataclasses import replace

import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.services.object_linking import (
    ObjectLinkError,
    copy_reference_object,
    link_object_to_reference,
    remember_object,
)


def _object(object_id: str) -> LabeledObject:
    return LabeledObject(
        object_id, "car", Box3D(1, 2, 3, 4, 2, 1.5, 0.3),
        source={"raw": {"id": object_id}},
        attributes={"name": "자동차"},
        extra_fields={"vendor": {"value": 7}},
    )


def _label(frame_id: str, *objects: LabeledObject) -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset", frame_id=frame_id,
        point_cloud_paths={"aeva": (f"{frame_id}.bin",)}, image_paths={},
        reference_frame="lidar:aeva", objects=objects,
    )


def test_backward_copy_preserves_id_and_destination_frame_identity() -> None:
    source = _label("003", _object("track-1"))
    target = replace(_label("001", _object("unrelated")), revision=3)
    reference = remember_object(source, "track-1", profile_id="profile")
    copied = copy_reference_object(target, reference, profile_id="profile")

    assert copied.frame_id == target.frame_id
    assert copied.point_cloud_paths == target.point_cloud_paths
    assert copied.revision == 3
    assert copied.objects[0] == target.objects[0]
    assert copied.objects[1].id == "track-1"
    assert copied.objects[1].box3d == source.objects[0].box3d
    assert copied.objects[1].source == source.objects[0].source
    assert copied.frame_status == "in_progress"
    assert len(source.objects) == len(target.objects) == 1
    assert "object_link_history" not in source.objects[0].extra_fields


def test_link_preserves_geometry_metadata_and_records_old_id() -> None:
    reference = remember_object(_label("003", _object("track-1")), "track-1", profile_id=None)
    selected = replace(_object("independent"), box3d=Box3D(10, 12, 2, 3, 2, 1, 0.5))
    target = _label("001", selected, _object("other"))
    linked = link_object_to_reference(target, selected.id, reference, profile_id=None)

    obj = linked.objects[0]
    assert obj.id == "track-1"
    assert obj.box3d == selected.box3d
    assert obj.attributes == selected.attributes
    assert obj.source == selected.source
    assert obj.extra_fields["vendor"] == selected.extra_fields["vendor"]
    assert obj.extra_fields["object_link_history"][0]["previous_object_id"] == "independent"
    assert obj.extra_fields["object_link_history"][0]["reference_frame_id"] == "003"
    assert linked.objects[1] == target.objects[1]
    assert target.objects[0].id == "independent"


@pytest.mark.parametrize("operation", ["copy", "link"])
def test_duplicate_id_never_overwrites_an_existing_object(operation: str) -> None:
    reference = remember_object(_label("003", _object("track-1")), "track-1", profile_id=None)
    target = _label("001", _object("independent"), _object("track-1"))
    with pytest.raises(ObjectLinkError, match="이미 있습니다"):
        if operation == "copy":
            copy_reference_object(target, reference, profile_id=None)
        else:
            link_object_to_reference(target, "independent", reference, profile_id=None)
    assert [obj.id for obj in target.objects] == ["independent", "track-1"]


@pytest.mark.parametrize("mismatch", ["dataset", "profile", "lidar", "coordinates"])
def test_reference_cannot_cross_dataset_profile_or_lidar(mismatch: str) -> None:
    reference = remember_object(_label("003", _object("track-1")), "track-1", profile_id="a")
    target = _label("001")
    profile_id = "a"
    if mismatch == "dataset":
        target = replace(target, dataset_id="another")
    elif mismatch == "profile":
        profile_id = "b"
    elif mismatch == "lidar":
        target = replace(target, point_cloud_paths={"other": ("001.bin",)})
    else:
        target = replace(target, reference_frame="other")
    with pytest.raises(ObjectLinkError, match="같은 데이터셋"):
        copy_reference_object(target, reference, profile_id=profile_id)


def test_class_mismatch_and_same_frame_link_are_rejected() -> None:
    reference = remember_object(_label("003", _object("track-1")), "track-1", profile_id=None)
    pedestrian = replace(_object("p"), class_name="pedestrian")
    with pytest.raises(ObjectLinkError, match="클래스"):
        link_object_to_reference(_label("001", pedestrian), "p", reference, profile_id=None)
    with pytest.raises(ObjectLinkError, match="다른 프레임"):
        link_object_to_reference(_label("003", _object("x")), "x", reference, profile_id=None)


def test_repeated_link_preserves_history_and_same_id_is_noop() -> None:
    ref_a = remember_object(_label("003", _object("a")), "a", profile_id=None)
    ref_b = remember_object(_label("004", _object("b")), "b", profile_id=None)
    original = _label("001", _object("original"))
    first = link_object_to_reference(original, "original", ref_a, profile_id=None)
    assert link_object_to_reference(first, "a", ref_a, profile_id=None) is first
    second = link_object_to_reference(first, "a", ref_b, profile_id=None)
    assert [entry["previous_object_id"] for entry in second.objects[0].extra_fields[
        "object_link_history"
    ]] == ["original", "a"]
    assert len(first.objects[0].extra_fields["object_link_history"]) == 1


def test_malformed_existing_history_is_not_overwritten() -> None:
    reference = remember_object(_label("003", _object("a")), "a", profile_id=None)
    original = replace(_object("b"), extra_fields={"object_link_history": {"vendor": 1}})
    with pytest.raises(ObjectLinkError, match="형식"):
        link_object_to_reference(_label("001", original), "b", reference, profile_id=None)
    assert original.extra_fields == {"object_link_history": {"vendor": 1}}
