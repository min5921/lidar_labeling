from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Callable, Literal


SensorKind = Literal["lidar", "camera"]
ProgressCallback = Callable[[int, int, Path], None]
CancelCheck = Callable[[], bool]

_LIDAR_SUFFIXES = {".bin", ".pcd"}
_CAMERA_SUFFIXES = {".jpg", ".jpeg", ".png"}
_IGNORED_PARTS = {
    ".git",
    ".lidar_label_tool",
    ".recovery",
    "annotations",
    "build",
    "dist",
    "exports",
    "generations",
    "release",
    "release_packages",
    "source_labels",
}
_GENERIC_LEAF_NAMES = {"frames", "images", "points", "pointcloud", "point_cloud"}
_SAFE_ID = re.compile(
    r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))"
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$"
)


class DatasetDiscoveryCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DiscoveredSample:
    source_sample_id: str
    relative_path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SensorCandidate:
    key: str
    kind: SensorKind
    suggested_id: str
    display_name: str
    format: str
    directory: str
    data_pattern: str
    samples: tuple[DiscoveredSample, ...]

    @property
    def sample_count(self) -> int:
        return len(self.samples)


@dataclass(frozen=True, slots=True)
class TimestampCandidate:
    relative_path: str
    columns: tuple[str, ...]
    read_error: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class DatasetDiscoveryResult:
    root: Path
    lidars: tuple[SensorCandidate, ...]
    cameras: tuple[SensorCandidate, ...]
    timestamps: tuple[TimestampCandidate, ...]
    issues: tuple[DiscoveryIssue, ...]


def discover_dataset(
    root: Path,
    *,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DatasetDiscoveryResult:
    """Inventory supported source files without modifying the selected root."""
    source_root = Path(root).resolve()
    if not source_root.is_dir():
        raise ValueError(f"dataset discovery root is not a directory: {source_root}")

    files, walk_issues = _inventory_files(source_root, cancel_check=cancel_check)
    groups: dict[tuple[SensorKind, str, str], list[Path]] = {}
    timestamp_paths: list[Path] = []
    total = len(files)
    for position, path in enumerate(files, start=1):
        _check_cancel(cancel_check)
        if progress is not None:
            progress(position, total, path)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            timestamp_paths.append(path)
            continue
        if suffix in _LIDAR_SUFFIXES:
            kind: SensorKind = "lidar"
        elif suffix in _CAMERA_SUFFIXES:
            kind = "camera"
        else:
            continue
        relative_parent = path.parent.relative_to(source_root).as_posix()
        groups.setdefault((kind, relative_parent, suffix), []).append(path)

    issues = list(walk_issues)
    candidates: list[SensorCandidate] = []
    used_ids: set[str] = set()
    for (kind, directory, suffix), paths in sorted(
        groups.items(), key=lambda item: _utf8_sort_key("\0".join(item[0]))
    ):
        ordered = sorted(paths, key=lambda path: _utf8_sort_key(_relative(source_root, path)))
        display_name = _display_name(ordered[0].parent, source_root, kind)
        suggested_id = _unique_suggested_id(
            _suggest_machine_id(display_name, kind, directory),
            used_ids,
            salt=f"{kind}\0{directory}\0{suffix}",
        )
        used_ids.add(suggested_id.casefold())
        samples = tuple(
            DiscoveredSample(
                source_sample_id=path.stem,
                relative_path=_relative(source_root, path),
                size_bytes=path.stat().st_size,
            )
            for path in ordered
        )
        if len({sample.source_sample_id for sample in samples}) != len(samples):
            issues.append(
                DiscoveryIssue(
                    "duplicate_source_sample_id",
                    f"{kind} 후보에 중복 stem이 있습니다: {directory}",
                    ordered[0].parent,
                )
            )
        candidates.append(
            SensorCandidate(
                key=f"{kind}:{directory}:{suffix}",
                kind=kind,
                suggested_id=suggested_id,
                display_name=display_name,
                format=suffix[1:],
                directory=directory,
                data_pattern=(
                    f"{directory}/{{sample_id}}{suffix}"
                    if directory != "."
                    else f"{{sample_id}}{suffix}"
                ),
                samples=samples,
            )
        )

    timestamp_candidates = tuple(
        _timestamp_candidate(path, source_root) for path in timestamp_paths
    )
    return DatasetDiscoveryResult(
        root=source_root,
        lidars=tuple(item for item in candidates if item.kind == "lidar"),
        cameras=tuple(item for item in candidates if item.kind == "camera"),
        timestamps=timestamp_candidates,
        issues=tuple(issues),
    )


def _inventory_files(
    root: Path,
    *,
    cancel_check: CancelCheck | None,
) -> tuple[list[Path], tuple[DiscoveryIssue, ...]]:
    files: list[Path] = []
    issues: list[DiscoveryIssue] = []

    def on_error(exc: OSError) -> None:
        issues.append(
            DiscoveryIssue(
                "directory_unreadable",
                f"폴더를 읽을 수 없습니다: {exc}",
                Path(exc.filename) if exc.filename else None,
            )
        )

    for current, directories, names in os.walk(root, topdown=True, onerror=on_error):
        _check_cancel(cancel_check)
        directories[:] = sorted(
            [name for name in directories if name.casefold() not in _IGNORED_PARTS],
            key=_utf8_sort_key,
        )
        current_path = Path(current)
        for name in sorted(names, key=_utf8_sort_key):
            path = current_path / name
            suffix = path.suffix.lower()
            if suffix not in _LIDAR_SUFFIXES | _CAMERA_SUFFIXES | {".csv"}:
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                issues.append(
                    DiscoveryIssue(
                        "path_escape",
                        "root 밖을 가리키는 파일 또는 symlink를 제외했습니다.",
                        path,
                    )
                )
                continue
            if resolved.is_file():
                files.append(resolved)
    files.sort(key=lambda path: _utf8_sort_key(_relative(root, path)))
    return files, tuple(issues)


def _timestamp_candidate(path: Path, root: Path) -> TimestampCandidate:
    import csv

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            columns = tuple(next(reader))
        if not columns or any(not column for column in columns):
            raise ValueError("CSV header has an empty column")
    except (OSError, UnicodeError, StopIteration, csv.Error, ValueError) as exc:
        return TimestampCandidate(
            relative_path=_relative(root, path),
            columns=(),
            read_error=f"{type(exc).__name__}: {exc}",
        )
    return TimestampCandidate(
        relative_path=_relative(root, path),
        columns=columns,
    )


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _display_name(parent: Path, root: Path, kind: SensorKind) -> str:
    name = parent.name
    if name.casefold() in _GENERIC_LEAF_NAMES and parent.parent != root.parent:
        name = parent.parent.name
    return name or kind


def _suggest_machine_id(display_name: str, kind: SensorKind, salt: str) -> str:
    lowered = display_name.casefold()
    ascii_parts = re.findall(r"[a-z0-9]+", lowered)
    candidate = "_".join(ascii_parts).strip("._-")
    if not candidate or not candidate[0].isalnum():
        candidate = f"{kind}_{hashlib.sha256(salt.encode('utf-8')).hexdigest()[:12]}"
    candidate = candidate[:64].rstrip(".")
    if _SAFE_ID.fullmatch(candidate):
        return candidate
    return f"{kind}_{hashlib.sha256(salt.encode('utf-8')).hexdigest()[:12]}"


def _unique_suggested_id(candidate: str, used: set[str], *, salt: str) -> str:
    if candidate.casefold() not in used:
        return candidate
    digest = hashlib.sha256(salt.encode("utf-8")).hexdigest()[:10]
    prefix = candidate[: 64 - len(digest) - 1].rstrip("._-")
    return f"{prefix}_{digest}"


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise DatasetDiscoveryCancelled("dataset discovery was cancelled")


def _utf8_sort_key(value: str) -> bytes:
    return value.encode("utf-8")
