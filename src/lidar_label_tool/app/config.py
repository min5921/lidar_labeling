from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    classes = data.get("classes")
    if not isinstance(classes, list) or not classes:
        raise ValueError("config.classes must be a non-empty list")
    class_names = {str(item["name"]) for item in classes}
    mappings = data.get("source_class_mappings", {})
    unknown_targets = set(mappings.values()) - class_names
    if unknown_targets:
        raise ValueError(f"class mappings reference unknown classes: {sorted(unknown_targets)}")
    return data


def default_config_path(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root / "configs" / "default.json"
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "configs" / "default.json"
    return Path(__file__).resolve().parents[3] / "configs" / "default.json"
