from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import tempfile


APP_DIRECTORY_NAME = "LiDARLabelTool"
CRASH_LOG_NAME = "LiDARLabelTool_crash.log"


def user_log_directory(
    env: Mapping[str, str] | None = None, *, home: Path | None = None
) -> Path:
    """Return the per-user Windows log directory without creating it."""
    values = os.environ if env is None else env
    local_app_data = values.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / APP_DIRECTORY_NAME / "logs"
    home_path = Path.home() if home is None else Path(home)
    return home_path / "AppData" / "Local" / APP_DIRECTORY_NAME / "logs"


def crash_log_candidates(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    fallback_root: Path | None = None,
) -> tuple[Path, ...]:
    primary = user_log_directory(env, home=home) / CRASH_LOG_NAME
    fallback = (
        Path(tempfile.gettempdir()) if fallback_root is None else Path(fallback_root)
    ) / APP_DIRECTORY_NAME / CRASH_LOG_NAME
    return (primary,) if primary == fallback else (primary, fallback)


def write_crash_log(
    details: str,
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    fallback_root: Path | None = None,
) -> Path | None:
    """Write diagnostics to a user-writable location without masking the crash."""
    for path in crash_log_candidates(
        env, home=home, fallback_root=fallback_root
    ):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(details, encoding="utf-8")
        except OSError:
            continue
        return path
    return None
