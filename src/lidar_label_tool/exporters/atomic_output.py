from __future__ import annotations

import os
from pathlib import Path


def require_new_export_path(target: Path) -> None:
    """Reject existing files, directories and dangling links before an export."""
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"export output already exists; choose a new path: {target}")


def publish_new_export(temporary: Path, target: Path) -> None:
    """Atomically publish a complete sibling file without replacing a racing writer.

    Hard-link creation is exclusive on Windows and POSIX. If the destination
    filesystem cannot support it, fail without falling back to a destructive
    replace or exposing a partially written output.
    """
    try:
        os.link(temporary, target)
    except FileExistsError:
        raise FileExistsError(
            f"export output already exists; choose a new path: {target}"
        ) from None
    except OSError as exc:
        raise OSError(
            f"cannot publish export safely; use a local filesystem supporting hard links: {target}"
        ) from exc
