from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lidar_label_tool.io.dataset_v2 import (
    load_dataset_manifest_v2,
    read_dataset_manifest_header,
)


@dataclass(frozen=True, slots=True)
class DatasetProfileChoice:
    id: str
    display_name: str
    lidar_id: str


def list_dataset_profiles(root: Path) -> tuple[DatasetProfileChoice, ...]:
    """Read v2 profile choices without loading points or exposing JSON to the UI."""
    if not (root / "dataset.json").is_file():
        if (root / "schema.json").is_file() and (root / "segment.json").is_file():
            return ()
        raise ValueError("supported dataset manifest was not found")
    header = read_dataset_manifest_header(root)
    if header.schema_version == "1.0":
        return ()
    manifest = load_dataset_manifest_v2(root)
    return tuple(
        DatasetProfileChoice(profile.id, profile.display_name, profile.lidar_id)
        for profile in manifest.profiles
    )
