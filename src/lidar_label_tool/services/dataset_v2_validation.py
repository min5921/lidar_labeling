from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

import numpy as np
from PIL import Image, UnidentifiedImageError

from lidar_label_tool.domain.dataset_v2 import (
    DatasetManifestV2,
    DatasetProfileV2,
    FrameIndexRecordV2,
    LidarSensorV2,
    TaxonomyV2,
)
from lidar_label_tool.io.dataset_v2 import (
    canonical_frame_index_bytes,
    load_dataset_manifest_v2,
    load_frame_index_v2,
    load_taxonomy_v2,
)
from lidar_label_tool.io.json_schema import (
    JsonDocumentError,
    JsonSchemaValidationError,
    read_json_document,
    validate_json_document,
)
from lidar_label_tool.geometry.transforms import validate_rigid_transform
from lidar_label_tool.services.timestamp_table import (
    TimestampTable,
    TimestampTableError,
    read_timestamp_table,
)


Severity = Literal["warning", "error"]


@dataclass(frozen=True, slots=True)
class DatasetV2ValidationIssue:
    severity: Severity
    code: str
    message: str
    path: Path | None = None
    profile_id: str | None = None
    frame_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": str(self.path) if self.path is not None else None,
            "profile_id": self.profile_id,
            "frame_id": self.frame_id,
        }


@dataclass(frozen=True, slots=True)
class ProfileFrameIndexV2:
    profile_id: str
    path: Path
    records: tuple[FrameIndexRecordV2, ...]


@dataclass(frozen=True, slots=True)
class DatasetV2ValidationReport:
    config_root: Path
    data_root: Path | None
    manifest: DatasetManifestV2 | None
    taxonomy: TaxonomyV2 | None
    frame_indexes: tuple[ProfileFrameIndexV2, ...]
    issues: tuple[DatasetV2ValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        return self.manifest is not None and self.error_count == 0

    @property
    def exit_code(self) -> int:
        if self.error_count:
            return 2
        if self.warning_count:
            return 1
        return 0

    def to_dict(self) -> dict[str, object]:
        manifest = self.manifest
        return {
            "schema_version": "2.0",
            "dataset_id": manifest.dataset_id if manifest is not None else None,
            "config_root": str(self.config_root),
            "data_root": str(self.data_root) if self.data_root is not None else None,
            "default_profile_id": (
                manifest.default_profile_id if manifest is not None else None
            ),
            "profiles": [
                {
                    "profile_id": item.profile_id,
                    "frame_index": str(item.path),
                    "frame_count": len(item.records),
                }
                for item in self.frame_indexes
            ],
            "valid": self.is_valid,
            "issue_counts": {
                "error": self.error_count,
                "warning": self.warning_count,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def require_valid(self) -> DatasetV2ValidationReport:
        if not self.is_valid:
            raise DatasetV2SemanticError(self)
        return self


class DatasetV2SemanticError(ValueError):
    def __init__(self, report: DatasetV2ValidationReport) -> None:
        self.report = report
        preview = "; ".join(
            f"{issue.code}: {issue.message}"
            for issue in report.issues
            if issue.severity == "error"
        )
        super().__init__(preview or "dataset v2 semantic validation failed")


def validate_dataset_v2(
    config_root: Path,
    *,
    schema_root: Path | None = None,
    verify_images: bool = True,
) -> DatasetV2ValidationReport:
    """Validate one v2 configuration root without modifying source or config files."""
    root = Path(config_root).resolve()
    try:
        manifest = load_dataset_manifest_v2(root, schema_root=schema_root)
    except (FileNotFoundError, JsonDocumentError, JsonSchemaValidationError) as exc:
        issue = DatasetV2ValidationIssue(
            severity="error",
            code="manifest_invalid",
            message=str(exc),
            path=root / "dataset.json",
        )
        return DatasetV2ValidationReport(
            config_root=root,
            data_root=None,
            manifest=None,
            taxonomy=None,
            frame_indexes=(),
            issues=(issue,),
        )
    return _DatasetV2Validator(
        root,
        manifest,
        schema_root,
        verify_images=verify_images,
    ).run()


def validate_dataset_manifest_v2(
    config_root: Path,
    manifest: DatasetManifestV2,
    *,
    schema_root: Path | None = None,
    verify_images: bool = True,
) -> DatasetV2ValidationReport:
    """Validate an uncommitted manifest against files under a configuration root."""
    return _DatasetV2Validator(
        Path(config_root).resolve(),
        manifest,
        schema_root,
        verify_images=verify_images,
    ).run()


class _DatasetV2Validator:
    def __init__(
        self,
        config_root: Path,
        manifest: DatasetManifestV2,
        schema_root: Path | None,
        *,
        verify_images: bool,
    ) -> None:
        self.config_root = config_root
        self.manifest = manifest
        self.schema_root = schema_root
        self.verify_images = verify_images
        self.data_root: Path | None = None
        self.taxonomy: TaxonomyV2 | None = None
        self.frame_indexes: list[ProfileFrameIndexV2] = []
        self.timestamp_tables: dict[str, TimestampTable] = {}
        self.calibration_image_sizes: dict[str, tuple[int, int]] = {}
        self.issues: list[DatasetV2ValidationIssue] = []

    def run(self) -> DatasetV2ValidationReport:
        self.data_root = self._resolve_data_root()
        self._validate_manifest_relations()
        self._validate_timestamp_sources()
        self._load_and_validate_taxonomy()
        for profile in self.manifest.profiles:
            self._validate_profile(profile)
        return DatasetV2ValidationReport(
            config_root=self.config_root,
            data_root=self.data_root,
            manifest=self.manifest,
            taxonomy=self.taxonomy,
            frame_indexes=tuple(self.frame_indexes),
            issues=tuple(self.issues),
        )

    def _add(
        self,
        code: str,
        message: str,
        *,
        severity: Severity = "error",
        path: Path | None = None,
        profile_id: str | None = None,
        frame_id: str | None = None,
    ) -> None:
        self.issues.append(
            DatasetV2ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                path=path,
                profile_id=profile_id,
                frame_id=frame_id,
            )
        )

    def _resolve_data_root(self) -> Path | None:
        spec = self.manifest.data_root
        if spec.kind == "manifest_relative":
            resolved = self._resolve_under(
                self.config_root,
                spec.path,
                code="unsafe_data_root",
            )
        else:
            candidate = Path(spec.path)
            if not candidate.is_absolute():
                self._add(
                    "unsafe_data_root",
                    f"absolute_local data_root is not absolute: {spec.path}",
                )
                return None
            resolved = candidate.resolve()
        if resolved is not None and not resolved.is_dir():
            self._add(
                "data_root_missing",
                f"data root is not a directory: {resolved}",
                path=resolved,
            )
        return resolved

    def _validate_manifest_relations(self) -> None:
        lidar_ids = [sensor.id for sensor in self.manifest.lidars]
        profile_ids = [profile.id for profile in self.manifest.profiles]
        sensor_ids = list(lidar_ids)
        if self.manifest.camera is not None:
            sensor_ids.append(self.manifest.camera.id)
        self._report_duplicates("sensor_id_duplicate", "sensor ID", sensor_ids)
        self._report_duplicates("profile_id_duplicate", "profile ID", profile_ids)
        if self.manifest.default_profile_id not in profile_ids:
            self._add(
                "default_profile_unknown",
                f"default profile does not exist: {self.manifest.default_profile_id}",
            )
        for profile in self.manifest.profiles:
            lidar = self.manifest.lidar(profile.lidar_id)
            if lidar is None:
                self._add(
                    "profile_lidar_unknown",
                    f"profile references unknown LiDAR: {profile.lidar_id}",
                    profile_id=profile.id,
                )
            if profile.camera is None:
                continue
            camera = self.manifest.camera
            if camera is None or profile.camera.camera_id != camera.id:
                self._add(
                    "profile_camera_unknown",
                    f"profile references unknown camera: {profile.camera.camera_id}",
                    profile_id=profile.id,
                )
                continue
            if profile.frame_index.generation.method == "timestamp_nearest":
                if lidar is None or lidar.timestamp is None or camera.timestamp is None:
                    self._add(
                        "timestamp_spec_missing",
                        "timestamp_nearest requires LiDAR and camera timestamp specs",
                        profile_id=profile.id,
                    )
                elif lidar.timestamp.clock_domain != camera.timestamp.clock_domain:
                    self._add(
                        "clock_domain_mismatch",
                        "timestamp_nearest sensors use different clock domains: "
                        f"{lidar.timestamp.clock_domain!r} != "
                        f"{camera.timestamp.clock_domain!r}",
                        profile_id=profile.id,
                    )

    def _validate_timestamp_sources(self) -> None:
        timestamps = [
            (sensor.id, sensor.timestamp) for sensor in self.manifest.lidars
        ]
        if self.manifest.camera is not None:
            timestamps.append(
                (self.manifest.camera.id, self.manifest.camera.timestamp)
            )
        for sensor_id, timestamp in timestamps:
            if timestamp is None:
                continue
            path = self._resolve_data_path(timestamp.path)
            if not self._validate_hashed_file(
                path,
                timestamp.sha256,
                missing_code="timestamp_file_missing",
                hash_code="timestamp_hash_mismatch",
            ):
                continue
            assert path is not None
            try:
                table = read_timestamp_table(
                    path,
                    sample_id_column=timestamp.sample_id_column,
                    value_column=timestamp.value_column,
                    unit=timestamp.unit,  # type: ignore[arg-type]
                    clock_domain=timestamp.clock_domain,
                    offset_ns=timestamp.offset_ns,
                )
            except TimestampTableError as exc:
                self._add(
                    exc.code,
                    str(exc),
                    path=path,
                )
                continue
            self.timestamp_tables[sensor_id] = table
            if table.reordered_row_count:
                self._add(
                    "timestamp_rows_reordered",
                    f"{sensor_id} CSV has {table.reordered_row_count} non-monotonic rows; "
                    "the frozen index uses deterministic sorting",
                    severity="warning",
                    path=path,
                )
            if table.duplicate_timestamp_count:
                self._add(
                    "timestamp_values_duplicate",
                    f"{sensor_id} CSV has {table.duplicate_timestamp_count} duplicate timestamps",
                    severity="warning",
                    path=path,
                )

    def _load_and_validate_taxonomy(self) -> None:
        reference = self.manifest.taxonomy
        path = self._resolve_config_path(reference.path)
        if not self._validate_hashed_file(
            path,
            reference.sha256,
            missing_code="taxonomy_missing",
            hash_code="taxonomy_hash_mismatch",
        ):
            return
        assert path is not None
        try:
            taxonomy = load_taxonomy_v2(path, schema_root=self.schema_root)
        except (FileNotFoundError, JsonDocumentError, JsonSchemaValidationError) as exc:
            self._add("taxonomy_invalid", str(exc), path=path)
            return
        self.taxonomy = taxonomy
        class_ids = [item.id for item in taxonomy.classes]
        self._report_duplicates("taxonomy_class_duplicate", "class ID", class_ids)
        shortcuts = [item.shortcut for item in taxonomy.classes if item.shortcut is not None]
        self._report_duplicates("taxonomy_shortcut_duplicate", "shortcut", shortcuts)
        aliases = [alias.casefold() for item in taxonomy.classes for alias in item.aliases]
        alias_counts = Counter(aliases)
        for alias, count in alias_counts.items():
            if count > 1:
                self._add(
                    "taxonomy_alias_duplicate",
                    f"taxonomy alias is duplicated: {alias!r}",
                    path=path,
                )
        class_set = set(class_ids)
        class_folded = {class_id.casefold() for class_id in class_ids}
        for alias in aliases:
            if alias in class_folded:
                self._add(
                    "taxonomy_alias_class_collision",
                    f"taxonomy alias collides with a class ID: {alias!r}",
                    path=path,
                )
        if taxonomy.fallback_class_id is not None and taxonomy.fallback_class_id not in class_set:
            self._add(
                "taxonomy_fallback_unknown",
                f"fallback class does not exist: {taxonomy.fallback_class_id}",
                path=path,
            )
        for namespace, mapping in taxonomy.source_mappings.items():
            for source, target in mapping.items():
                if target not in class_set:
                    self._add(
                        "taxonomy_mapping_unknown",
                        f"{namespace}.{source} maps to unknown class {target!r}",
                        path=path,
                    )

    def _validate_calibration(
        self,
        profile: DatasetProfileV2,
        lidar: LidarSensorV2 | None,
    ) -> None:
        assert profile.camera is not None
        path = self._resolve_config_path(
            profile.camera.calibration_path or "",
            severity="warning",
            profile_id=profile.id,
        )
        if not self._validate_hashed_file(
            path,
            profile.camera.calibration_sha256 or "",
            missing_code="calibration_missing",
            hash_code="calibration_hash_mismatch",
            severity="warning",
            profile_id=profile.id,
        ):
            return
        assert path is not None
        try:
            document = read_json_document(path)
            validate_json_document(
                document,
                "calibration.schema.json",
                resource_root=self.schema_root,
            )
        except (JsonDocumentError, JsonSchemaValidationError, FileNotFoundError) as exc:
            self._add(
                "calibration_invalid",
                str(exc),
                severity="warning",
                path=path,
                profile_id=profile.id,
            )
            return
        if not isinstance(document, Mapping):
            self._add(
                "calibration_invalid",
                "calibration root must be an object",
                severity="warning",
                path=path,
                profile_id=profile.id,
            )
            return
        if lidar is not None and document.get("reference_frame") != lidar.coordinate_frame:
            self._add(
                "calibration_reference_mismatch",
                "calibration reference_frame does not equal the active LiDAR label frame; "
                "projection will remain disabled",
                severity="warning",
                path=path,
                profile_id=profile.id,
            )
            return
        cameras = document.get("cameras")
        camera_document = (
            cameras.get(profile.camera.camera_id)
            if isinstance(cameras, Mapping)
            else None
        )
        if not isinstance(camera_document, Mapping):
            self._add(
                "calibration_camera_missing",
                f"calibration has no camera {profile.camera.camera_id!r}",
                severity="warning",
                path=path,
                profile_id=profile.id,
            )
            return
        try:
            validate_rigid_transform(camera_document["T_camera_reference"])
            if "correction_delta" in camera_document:
                validate_rigid_transform(camera_document["correction_delta"])
            intrinsic = np.asarray(camera_document["intrinsic"], dtype=np.float64)
            if intrinsic.shape != (3, 3) or not np.isfinite(intrinsic).all():
                raise ValueError("camera intrinsic must be a finite 3x3 matrix")
            width, height = (int(value) for value in camera_document["image_size"])
        except (KeyError, TypeError, ValueError) as exc:
            self._add(
                "calibration_numeric_invalid",
                str(exc),
                severity="warning",
                path=path,
                profile_id=profile.id,
            )
            return
        self.calibration_image_sizes[profile.id] = (width, height)

    def _validate_profile(self, profile: DatasetProfileV2) -> None:
        lidar = self.manifest.lidar(profile.lidar_id)
        if profile.camera is not None and profile.camera.mode == "calibrated":
            self._validate_calibration(profile, lidar)
        index_path = self._resolve_config_path(profile.frame_index.path)
        if not self._validate_hashed_file(
            index_path,
            profile.frame_index.sha256,
            missing_code="frame_index_missing",
            hash_code="frame_index_hash_mismatch",
            profile_id=profile.id,
        ):
            return
        assert index_path is not None
        try:
            raw = index_path.read_bytes()
            records = load_frame_index_v2(index_path, schema_root=self.schema_root)
        except (OSError, JsonDocumentError, JsonSchemaValidationError) as exc:
            self._add(
                "frame_index_invalid",
                str(exc),
                path=index_path,
                profile_id=profile.id,
            )
            return
        if raw != canonical_frame_index_bytes(records):
            self._add(
                "frame_index_not_canonical",
                "frame index is not canonical UTF-8 JSONL with LF and final newline",
                path=index_path,
                profile_id=profile.id,
            )
        if len(records) != profile.frame_index.frame_count:
            self._add(
                "frame_count_mismatch",
                f"manifest frame_count={profile.frame_index.frame_count}, "
                f"index records={len(records)}",
                path=index_path,
                profile_id=profile.id,
            )
        self.frame_indexes.append(
            ProfileFrameIndexV2(
                profile_id=profile.id,
                path=index_path,
                records=records,
            )
        )
        if lidar is None:
            return
        self._validate_records(profile, lidar, records)

    def _validate_records(
        self,
        profile: DatasetProfileV2,
        lidar: LidarSensorV2,
        records: tuple[FrameIndexRecordV2, ...],
    ) -> None:
        frame_ids: set[str] = set()
        lidar_samples: set[str] = set()
        lidar_source_samples: set[str] = set()
        lidar_paths: set[str] = set()
        generation = profile.frame_index.generation
        expected_order = sorted(
            records,
            key=lambda item: self._record_sort_key(item, lidar),
        )
        if tuple(item.frame_id for item in records) != tuple(
            item.frame_id for item in expected_order
        ):
            self._add(
                "frame_order_invalid",
                "frame index order does not follow timestamp/logical sample ordering",
                profile_id=profile.id,
            )
        camera_usage: Counter[str] = Counter()
        camera_sequence: list[str | None] = []
        for expected_ordinal, record in enumerate(records):
            if record.ordinal != expected_ordinal:
                self._record_issue(
                    "frame_ordinal_invalid",
                    record,
                    profile,
                    f"expected ordinal {expected_ordinal}, got {record.ordinal}",
                )
            self._check_unique(
                frame_ids,
                record.frame_id,
                "frame_id_duplicate",
                "frame ID",
                record,
                profile,
            )
            self._check_unique(
                lidar_samples,
                record.lidar.sample_id,
                "lidar_sample_duplicate",
                "LiDAR logical sample ID",
                record,
                profile,
            )
            self._check_unique(
                lidar_source_samples,
                record.lidar.source_sample_id,
                "lidar_source_sample_duplicate",
                "LiDAR source sample ID",
                record,
                profile,
            )
            self._check_unique(
                lidar_paths,
                record.lidar.path,
                "lidar_path_duplicate",
                "LiDAR path",
                record,
                profile,
            )
            if record.profile_id != profile.id:
                self._record_issue(
                    "frame_profile_mismatch",
                    record,
                    profile,
                    f"record profile {record.profile_id!r} != {profile.id!r}",
                )
            if record.lidar.sensor_id != profile.lidar_id:
                self._record_issue(
                    "frame_lidar_mismatch",
                    record,
                    profile,
                    f"record LiDAR {record.lidar.sensor_id!r} != {profile.lidar_id!r}",
                )
            if record.frame_id != record.lidar.sample_id:
                self._record_issue(
                    "frame_binding_mismatch",
                    record,
                    profile,
                    "frame_id must equal the LiDAR logical sample_id",
                )
            if record.match.method != generation.method:
                self._record_issue(
                    "sync_method_mismatch",
                    record,
                    profile,
                    f"record method {record.match.method!r} != {generation.method!r}",
                )
            if record.match.tolerance_ns != generation.tolerance_ns:
                self._record_issue(
                    "sync_tolerance_mismatch",
                    record,
                    profile,
                    "record tolerance does not match the profile generation",
                )
            self._validate_lidar_path(record, profile, lidar)
            self._validate_camera_binding(record, profile)
            self._validate_record_timestamps(record, profile)
            camera_id = record.camera.sample_id if record.camera is not None else None
            camera_sequence.append(camera_id)
            if camera_id is not None:
                camera_usage[camera_id] += 1
        matched = sum(camera_usage.values())
        if profile.camera is not None and matched == 0:
            self._add(
                "camera_match_zero",
                "profile camera has no matched frames; LiDAR frames remain usable",
                severity="warning",
                profile_id=profile.id,
            )
        reuse = sum(count - 1 for count in camera_usage.values())
        repeat_run = _max_repeat_run(camera_sequence)
        if matched and (reuse / matched > 0.5 or repeat_run > 3):
            self._add(
                "camera_reuse_high",
                f"camera reuse={reuse}, maximum consecutive run={repeat_run}",
                severity="warning",
                profile_id=profile.id,
            )

    def _record_sort_key(
        self,
        record: FrameIndexRecordV2,
        lidar: LidarSensorV2,
    ) -> tuple[object, ...]:
        table = self.timestamp_tables.get(lidar.id)
        timestamp = (
            table.timestamp_for(record.lidar.source_sample_id)
            if table is not None
            else None
        )
        if timestamp is not None:
            return (0, timestamp, record.lidar.sample_id.encode("utf-8"))
        return (1, record.lidar.sample_id.encode("utf-8"))

    def _validate_record_timestamps(
        self,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
    ) -> None:
        lidar_table = self.timestamp_tables.get(record.lidar.sensor_id)
        if lidar_table is not None:
            expected = lidar_table.timestamp_for(record.lidar.source_sample_id)
            if expected is None:
                self._record_issue(
                    "lidar_timestamp_row_missing",
                    record,
                    profile,
                    "LiDAR source sample has no timestamp CSV row",
                )
            elif record.lidar.timestamp_ns != expected:
                self._record_issue(
                    "lidar_timestamp_mismatch",
                    record,
                    profile,
                    f"record timestamp={record.lidar.timestamp_ns}, CSV timestamp={expected}",
                )
        camera = record.camera
        if camera is None:
            return
        camera_table = self.timestamp_tables.get(camera.sensor_id)
        if camera_table is None:
            return
        expected_camera = camera_table.timestamp_for(camera.source_sample_id)
        if expected_camera is None:
            self._record_issue(
                "camera_timestamp_row_missing",
                record,
                profile,
                "matched camera source sample has no timestamp CSV row",
                severity="warning",
            )
        elif camera.timestamp_ns is not None and camera.timestamp_ns != expected_camera:
            self._record_issue(
                "camera_timestamp_mismatch",
                record,
                profile,
                f"record timestamp={camera.timestamp_ns}, CSV timestamp={expected_camera}",
            )

    def _validate_lidar_path(
        self,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
        lidar: LidarSensorV2,
    ) -> None:
        path = self._resolve_data_path(record.lidar.path)
        if path is None or not path.is_file():
            self._record_issue(
                "lidar_file_missing",
                record,
                profile,
                f"LiDAR file does not exist: {record.lidar.path}",
                path=path,
            )
            return
        expected_suffix = f".{lidar.format}"
        if path.suffix.lower() != expected_suffix:
            self._record_issue(
                "lidar_format_mismatch",
                record,
                profile,
                f"expected {expected_suffix}, got {path.suffix}",
                path=path,
            )
            return
        try:
            size = path.stat().st_size
        except OSError as exc:
            self._record_issue(
                "lidar_file_unreadable",
                record,
                profile,
                str(exc),
                path=path,
            )
            return
        if size == 0:
            self._record_issue(
                "lidar_file_empty",
                record,
                profile,
                "LiDAR file is empty",
                path=path,
            )
        elif lidar.format == "bin" and size % lidar.point_spec.point_stride_bytes:
            self._record_issue(
                "lidar_stride_invalid",
                record,
                profile,
                f"file size {size} is not divisible by stride "
                f"{lidar.point_spec.point_stride_bytes}",
                path=path,
            )

    def _validate_camera_binding(
        self,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
    ) -> None:
        camera = record.camera
        if camera is None:
            return
        manifest_camera = self.manifest.camera
        if profile.camera is None or manifest_camera is None:
            self._record_issue(
                "unexpected_camera_binding",
                record,
                profile,
                "frame has a camera binding but the profile has no camera",
            )
            return
        if camera.sensor_id != profile.camera.camera_id:
            self._record_issue(
                "frame_camera_mismatch",
                record,
                profile,
                f"record camera {camera.sensor_id!r} != {profile.camera.camera_id!r}",
            )
        path = self._resolve_data_path(camera.path)
        if path is None or not path.is_file():
            self._record_issue(
                "camera_file_missing",
                record,
                profile,
                f"camera file does not exist: {camera.path}",
                path=path,
                severity="warning",
            )
        elif path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            self._record_issue(
                "camera_format_invalid",
                record,
                profile,
                f"unsupported camera image extension: {path.suffix}",
                path=path,
                severity="warning",
            )
        elif self.verify_images:
            self._validate_camera_image(path, record, profile)
        if record.match.method == "exact_stem":
            if record.lidar.source_sample_id != camera.source_sample_id:
                self._record_issue(
                    "exact_stem_mismatch",
                    record,
                    profile,
                    "exact_stem record uses different source sample IDs",
                )
        elif record.match.method == "timestamp_nearest":
            lidar_time = record.lidar.timestamp_ns
            camera_time = camera.timestamp_ns
            delta = camera.delta_ns
            tolerance = record.match.tolerance_ns
            if None in {lidar_time, camera_time, delta, tolerance}:
                self._record_issue(
                    "timestamp_binding_incomplete",
                    record,
                    profile,
                    "matched timestamp record has null timestamp/delta/tolerance",
                )
                return
            assert lidar_time is not None
            assert camera_time is not None
            assert delta is not None
            assert tolerance is not None
            expected_delta = camera_time - lidar_time
            if delta != expected_delta:
                self._record_issue(
                    "timestamp_delta_invalid",
                    record,
                    profile,
                    f"delta_ns={delta}, expected {expected_delta}",
                )
            if abs(delta) > tolerance:
                self._record_issue(
                    "timestamp_tolerance_exceeded",
                    record,
                    profile,
                    f"abs(delta_ns)={abs(delta)} > tolerance_ns={tolerance}",
                )

    def _validate_camera_image(
        self,
        path: Path,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
    ) -> None:
        try:
            with Image.open(path) as image:
                size = image.size
                image.verify()
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            self._record_issue(
                "camera_decode_failed",
                record,
                profile,
                f"camera image cannot be decoded: {exc}",
                path=path,
                severity="warning",
            )
            return
        expected = self.calibration_image_sizes.get(profile.id)
        if expected is not None and size != expected:
            self._record_issue(
                "calibration_image_size_mismatch",
                record,
                profile,
                f"image size={size}, calibration image_size={expected}; projection disabled",
                path=path,
                severity="warning",
            )

    def _resolve_config_path(
        self,
        value: str,
        *,
        severity: Severity = "error",
        profile_id: str | None = None,
    ) -> Path | None:
        return self._resolve_under(
            self.config_root,
            value,
            code="unsafe_config_path",
            severity=severity,
            profile_id=profile_id,
        )

    def _resolve_data_path(self, value: str) -> Path | None:
        if self.data_root is None:
            return None
        return self._resolve_under(self.data_root, value, code="unsafe_data_path")

    def _resolve_under(
        self,
        root: Path,
        value: str,
        *,
        code: str,
        severity: Severity = "error",
        profile_id: str | None = None,
    ) -> Path | None:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or "\\" in value:
            self._add(
                code,
                f"unsafe relative path: {value}",
                severity=severity,
                profile_id=profile_id,
            )
            return None
        candidate = root.joinpath(*pure.parts).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._add(
                code,
                f"path escapes configured root: {value}",
                severity=severity,
                path=candidate,
                profile_id=profile_id,
            )
            return None
        return candidate

    def _validate_hashed_file(
        self,
        path: Path | None,
        expected_sha256: str,
        *,
        missing_code: str,
        hash_code: str,
        severity: Severity = "error",
        profile_id: str | None = None,
    ) -> bool:
        if path is None:
            return False
        if not path.is_file():
            self._add(
                missing_code,
                f"file does not exist: {path}",
                severity=severity,
                path=path,
                profile_id=profile_id,
            )
            return False
        try:
            actual = _sha256(path)
        except OSError as exc:
            self._add(
                missing_code,
                f"cannot read file: {exc}",
                severity=severity,
                path=path,
                profile_id=profile_id,
            )
            return False
        if actual != expected_sha256:
            self._add(
                hash_code,
                f"SHA-256 mismatch: expected {expected_sha256}, got {actual}",
                severity=severity,
                path=path,
                profile_id=profile_id,
            )
            return False
        return True

    def _report_duplicates(self, code: str, label: str, values: list[str]) -> None:
        counts = Counter(value.casefold() for value in values)
        for value, count in counts.items():
            if count > 1:
                self._add(code, f"duplicate {label}: {value!r}")

    def _check_unique(
        self,
        seen: set[str],
        value: str,
        code: str,
        label: str,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
    ) -> None:
        folded = value.casefold()
        if folded in seen:
            self._record_issue(
                code,
                record,
                profile,
                f"duplicate {label}: {value!r}",
            )
        seen.add(folded)

    def _record_issue(
        self,
        code: str,
        record: FrameIndexRecordV2,
        profile: DatasetProfileV2,
        message: str,
        *,
        path: Path | None = None,
        severity: Severity = "error",
    ) -> None:
        self._add(
            code,
            message,
            severity=severity,
            path=path,
            profile_id=profile.id,
            frame_id=record.frame_id,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_repeat_run(values: list[str | None]) -> int:
    maximum = 0
    current = 0
    previous: str | None = None
    for value in values:
        if value is None:
            previous = None
            current = 0
            continue
        if value == previous:
            current += 1
        else:
            previous = value
            current = 1
        maximum = max(maximum, current)
    return maximum
