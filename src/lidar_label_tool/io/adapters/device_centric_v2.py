from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from lidar_label_tool.domain.dataset_v2 import (
    DatasetManifestV2,
    DatasetProfileV2,
    FrameIndexRecordV2,
    LidarSensorV2,
    TaxonomyV2,
)
from lidar_label_tool.domain.label_identity_v2 import (
    frame_record_sha256,
    lidar_binding_sha256,
    profile_identity_sha256,
)
from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec
from lidar_label_tool.io.dataset import DatasetIndex, SourceFrameData
from lidar_label_tool.io.dataset_v2 import (
    load_dataset_manifest_v2,
    load_frame_index_v2,
    load_taxonomy_v2,
    read_dataset_manifest_header,
)
from lidar_label_tool.io.json_schema import validate_json_document
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader
from lidar_label_tool.io.loaders.pcd_loader import PcdPointCloudLoader


class DeviceCentricV2Adapter:
    """Runtime adapter for one immutable v2 LiDAR profile."""

    name = "device_centric_v2"

    def __init__(self, config_root: Path, profile_id: str | None = None) -> None:
        self.root = Path(config_root).resolve()
        self.configuration_root = self.root
        self.requested_profile_id = profile_id
        self._manifest: DatasetManifestV2 | None = None
        self._profile: DatasetProfileV2 | None = None
        self._lidar: LidarSensorV2 | None = None
        self._taxonomy: TaxonomyV2 | None = None
        self._data_root: Path | None = None
        self._records: dict[str, FrameIndexRecordV2] = {}
        self._index: DatasetIndex | None = None
        self._camera_calibrations: dict[str, Any] = {}
        self._bin_loader = BinaryPointCloudLoader()
        self._pcd_loader = PcdPointCloudLoader()

    @classmethod
    def can_open(cls, root: Path) -> bool:
        try:
            header = read_dataset_manifest_header(Path(root))
        except (OSError, ValueError):
            return False
        return header.schema_version == "2.0" and header.layout == "device_centric_v2"

    @property
    def manifest(self) -> DatasetManifestV2:
        if self._manifest is None:
            self.scan()
        assert self._manifest is not None
        return self._manifest

    @property
    def profile(self) -> DatasetProfileV2:
        if self._profile is None:
            self.scan()
        assert self._profile is not None
        return self._profile

    @property
    def active_lidar(self) -> LidarSensorV2:
        if self._lidar is None:
            self.scan()
        assert self._lidar is not None
        return self._lidar

    @property
    def taxonomy(self) -> TaxonomyV2:
        if self._taxonomy is None:
            self.scan()
        assert self._taxonomy is not None
        return self._taxonomy

    @property
    def data_root(self) -> Path:
        if self._data_root is None:
            self.scan()
        assert self._data_root is not None
        return self._data_root

    @property
    def index(self) -> DatasetIndex:
        return self._index or self.scan()

    @property
    def camera_calibrations(self) -> Mapping[str, Any]:
        if self._index is None:
            self.scan()
        return self._camera_calibrations

    @property
    def camera_calibration_count(self) -> int:
        return len(self.camera_calibrations)

    @property
    def profile_sha256(self) -> str:
        return profile_identity_sha256(self.manifest, self.profile, self.active_lidar)

    @property
    def manifest_sha256(self) -> str:
        return _sha256(self.configuration_root / "dataset.json")

    def scan(self) -> DatasetIndex:
        if not self.can_open(self.root):
            raise ValueError(f"not a device-centric v2 dataset: {self.root}")
        manifest = load_dataset_manifest_v2(self.root)
        profile_id = self.requested_profile_id or manifest.default_profile_id
        profile = manifest.profile(profile_id)
        if profile is None:
            raise ValueError(f"unknown v2 profile: {profile_id}")
        lidar = manifest.lidar(profile.lidar_id)
        if lidar is None:
            raise ValueError(f"profile references unknown LiDAR: {profile.lidar_id}")
        data_root = _resolve_data_root(self.root, manifest)
        index_path = _safe_config_path(self.root, profile.frame_index.path)
        if _sha256(index_path) != profile.frame_index.sha256:
            raise ValueError(f"frame index fingerprint mismatch: {index_path}")
        records = load_frame_index_v2(index_path)
        if len(records) != profile.frame_index.frame_count:
            raise ValueError("frame index record count does not match manifest")
        record_map: dict[str, FrameIndexRecordV2] = {}
        for expected_ordinal, record in enumerate(records):
            if record.ordinal != expected_ordinal:
                raise ValueError(f"invalid frame ordinal: {record.ordinal}")
            if record.profile_id != profile.id or record.lidar.sensor_id != lidar.id:
                raise ValueError(f"frame index identity mismatch: {record.frame_id}")
            if record.frame_id != record.lidar.sample_id:
                raise ValueError(f"frame/LiDAR binding mismatch: {record.frame_id}")
            if record.frame_id in record_map:
                raise ValueError(f"duplicate frame ID: {record.frame_id}")
            record_map[record.frame_id] = record
        taxonomy_path = _safe_config_path(self.root, manifest.taxonomy.path)
        if _sha256(taxonomy_path) != manifest.taxonomy.sha256:
            raise ValueError(f"taxonomy fingerprint mismatch: {taxonomy_path}")
        taxonomy = load_taxonomy_v2(taxonomy_path)

        self._manifest = manifest
        self._profile = profile
        self._lidar = lidar
        self._taxonomy = taxonomy
        self._data_root = data_root
        self._records = record_map
        self._load_calibration()
        camera_ids = (
            (profile.camera.camera_id,)
            if profile.camera is not None and manifest.camera is not None
            else ()
        )
        self._index = DatasetIndex(
            root=self.root,
            dataset_id=manifest.dataset_id,
            adapter_name=self.name,
            frame_ids=tuple(record_map),
            lidar_ids=(lidar.id,),
            camera_ids=camera_ids,
            reference_frame=lidar.coordinate_frame,
            point_spec=lidar.point_spec,
            profile_id=profile.id,
            configuration_root=self.configuration_root,
        )
        return self._index

    def frame_record(self, frame_id: str) -> FrameIndexRecordV2:
        if not self._records:
            self.scan()
        try:
            return self._records[frame_id]
        except KeyError as exc:
            raise KeyError(f"unknown v2 frame: {frame_id}") from exc

    def point_spec_for(self, sensor_id: str) -> PointCloudSpec:
        if sensor_id != self.active_lidar.id:
            raise KeyError(
                f"profile {self.profile.id!r} has only active LiDAR {self.active_lidar.id!r}"
            )
        return self.active_lidar.point_spec

    def load_source_frame(self, frame_id: str) -> SourceFrameData:
        record = self.frame_record(frame_id)
        lidar_path = _safe_data_path(self.data_root, record.lidar.path)
        point_paths = {self.active_lidar.id: (lidar_path,)}
        image_paths: dict[str, Path] = {}
        if record.camera is not None:
            image_path = _safe_data_path(self.data_root, record.camera.path)
            if image_path.is_file():
                image_paths[record.camera.sensor_id] = image_path
        camera_delta = record.camera.delta_ns if record.camera is not None else None
        metadata = {
            "schema_version": "2.0",
            "profile_id": self.profile.id,
            "label_lidar_id": self.active_lidar.id,
            "reference_frame": self.active_lidar.coordinate_frame,
            "sensor_status": {self.active_lidar.id: "not_required"},
            "configuration_root": str(self.configuration_root),
            "frame_index_path": self.profile.frame_index.path,
            "frame_index_sha256": self.profile.frame_index.sha256,
            "profile_sha256": self.profile_sha256,
            "lidar_binding_sha256": lidar_binding_sha256(record),
            "frame_record_sha256": frame_record_sha256(record),
            "taxonomy_path": self.manifest.taxonomy.path,
            "taxonomy_sha256": self.manifest.taxonomy.sha256,
            "manifest_sha256": self.manifest_sha256,
            "timestamp_ns": record.lidar.timestamp_ns,
            "camera_delta_ns": camera_delta,
            "camera_mode": (
                self.profile.camera.mode if self.profile.camera is not None else "none"
            ),
            "calibration_path": (
                self.profile.camera.calibration_path
                if self.profile.camera is not None
                else None
            ),
        }
        return SourceFrameData(
            dataset_root=self.data_root,
            dataset_id=self.manifest.dataset_id,
            frame_id=record.frame_id,
            point_cloud_paths=point_paths,
            image_paths=image_paths,
            source_label_paths={},
            point_spec=self.active_lidar.point_spec,
            timestamp_micros=(
                str(record.lidar.timestamp_ns // 1_000)
                if record.lidar.timestamp_ns is not None
                else None
            ),
            metadata=metadata,
        )

    def load_cloud_from_source(
        self,
        frame: SourceFrameData,
        sensor_id: str,
        return_id: str = "1",
    ) -> PointCloudData:
        if sensor_id != self.active_lidar.id:
            raise KeyError(f"inactive LiDAR is not available in this profile: {sensor_id}")
        if return_id != "1":
            raise KeyError(f"v2 label-ready LiDAR has only return '1': {return_id}")
        paths = frame.point_cloud_paths.get(sensor_id)
        if not paths:
            raise KeyError(f"LiDAR {sensor_id!r} is missing in frame {frame.frame_id}")
        path = paths[0]
        loader = self._pcd_loader if path.suffix.lower() == ".pcd" else self._bin_loader
        if not loader.can_load(path, self.active_lidar.point_spec):
            raise ValueError(f"unsupported point cloud file: {path}")
        return loader.load(
            path,
            self.active_lidar.point_spec,
            sensor_id=sensor_id,
            return_id="1",
        )

    def _load_calibration(self) -> None:
        self._camera_calibrations = {}
        profile = self.profile
        if profile.camera is None or profile.camera.mode != "calibrated":
            return
        assert profile.camera.calibration_path is not None
        try:
            path = _safe_config_path(
                self.configuration_root,
                profile.camera.calibration_path,
            )
            if _sha256(path) != profile.camera.calibration_sha256:
                return
            with path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
            validate_json_document(document, "calibration.schema.json")
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(document, Mapping):
            return
        if document.get("reference_frame") != self.active_lidar.coordinate_frame:
            return
        cameras = document.get("cameras", {})
        if isinstance(cameras, Mapping):
            value = cameras.get(profile.camera.camera_id)
            if isinstance(value, Mapping):
                self._camera_calibrations[profile.camera.camera_id] = dict(value)


def _resolve_data_root(config_root: Path, manifest: DatasetManifestV2) -> Path:
    if manifest.data_root.kind == "manifest_relative":
        return _safe_config_path(config_root, manifest.data_root.path, require_file=False)
    path = Path(manifest.data_root.path)
    if not path.is_absolute():
        raise ValueError(f"absolute_local data root is not absolute: {path}")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValueError(f"v2 data root is not a directory: {resolved}")
    return resolved


def _safe_config_path(
    root: Path,
    value: str,
    *,
    require_file: bool = True,
) -> Path:
    candidate = _safe_path(root, value)
    if require_file and not candidate.is_file():
        raise ValueError(f"configuration file does not exist: {candidate}")
    if not require_file and not candidate.is_dir():
        raise ValueError(f"configuration directory does not exist: {candidate}")
    return candidate


def _safe_data_path(root: Path, value: str) -> Path:
    return _safe_path(root, value)


def _safe_path(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise ValueError(f"unsafe relative path: {value}")
    candidate = root.joinpath(*pure.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes configured root: {value}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
