from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(frozen=True, slots=True)
class SchemaViolation:
    pointer: str
    message: str


class JsonDocumentError(ValueError):
    """A JSON document could not be read as a valid object."""


class JsonSchemaValidationError(ValueError):
    """A JSON document violates one or more project schema rules."""

    def __init__(
        self,
        schema_name: str,
        violations: tuple[SchemaViolation, ...],
    ) -> None:
        self.schema_name = schema_name
        self.violations = violations
        preview = "; ".join(
            f"{item.pointer}: {item.message}" for item in violations[:5]
        )
        if len(violations) > 5:
            preview += f"; ... and {len(violations) - 5} more"
        super().__init__(f"{schema_name} validation failed: {preview}")


def schema_resource_path(name: str, resource_root: Path | None = None) -> Path:
    """Resolve a bundled read-only JSON schema in development or packaged runs."""
    if resource_root is not None:
        candidate = Path(resource_root) / name
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(candidate)

    frozen_root = getattr(sys, "_MEIPASS", None)
    candidates = []
    if frozen_root:
        candidates.append(Path(frozen_root) / "schemas" / name)
    candidates.extend(
        [
            Path(sys.prefix)
            / "share"
            / "lidar-label-tool"
            / "schemas"
            / name,
            Path(__file__).resolve().parents[3] / "schemas" / name,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"bundled schema not found: {name}")


def read_json_document(path: Path) -> Any:
    document_path = Path(path)
    try:
        with document_path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JsonDocumentError(
            f"cannot read JSON document {document_path}: {type(exc).__name__}: {exc}"
        ) from exc


def validate_json_document(
    document: Any,
    schema_name: str,
    *,
    resource_root: Path | None = None,
) -> None:
    schema = read_json_document(schema_resource_path(schema_name, resource_root))
    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )
    if not errors:
        return
    violations = tuple(
        SchemaViolation(
            pointer=_json_pointer(tuple(error.absolute_path)),
            message=error.message,
        )
        for error in errors
    )
    raise JsonSchemaValidationError(schema_name, violations)


def _json_pointer(parts: tuple[object, ...]) -> str:
    if not parts:
        return "/"
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)
