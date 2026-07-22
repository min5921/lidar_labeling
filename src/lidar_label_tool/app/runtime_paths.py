from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys
import tempfile


APP_DIRECTORY_NAME = "LiDARLabelTool"
CRASH_LOG_NAME = "LiDARLabelTool_crash.log"
SETTINGS_NAME = "settings.ini"


def _platform(platform_name: str | None) -> str:
    return sys.platform if platform_name is None else platform_name


def _home(home: Path | None) -> Path:
    return Path.home() if home is None else Path(home)


def _xdg_directory(
    values: Mapping[str, str],
    variable: str,
    fallback: Path,
) -> Path:
    configured = values.get(variable, "").strip()
    return Path(configured) if configured else fallback


def user_log_directory(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the platform-specific per-user log directory without creating it."""
    values = os.environ if env is None else env
    home_path = _home(home)
    if _platform(platform_name) == "win32":
        local_app_data = values.get("LOCALAPPDATA", "").strip()
        root = (
            Path(local_app_data)
            if local_app_data
            else home_path / "AppData" / "Local"
        )
        return root / APP_DIRECTORY_NAME / "logs"
    state_root = _xdg_directory(
        values,
        "XDG_STATE_HOME",
        home_path / ".local" / "state",
    )
    return state_root / APP_DIRECTORY_NAME / "logs"


def user_data_directory(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the per-user application data directory without creating it."""
    values = os.environ if env is None else env
    home_path = _home(home)
    if _platform(platform_name) == "win32":
        local_app_data = values.get("LOCALAPPDATA", "").strip()
        root = (
            Path(local_app_data)
            if local_app_data
            else home_path / "AppData" / "Local"
        )
        return root / APP_DIRECTORY_NAME
    data_root = _xdg_directory(
        values,
        "XDG_DATA_HOME",
        home_path / ".local" / "share",
    )
    return data_root / APP_DIRECTORY_NAME


def user_config_directory(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Return the platform-specific per-user configuration directory."""
    values = os.environ if env is None else env
    home_path = _home(home)
    if _platform(platform_name) == "win32":
        return user_data_directory(
            values,
            home=home_path,
            platform_name="win32",
        )
    config_root = _xdg_directory(
        values,
        "XDG_CONFIG_HOME",
        home_path / ".config",
    )
    return config_root / APP_DIRECTORY_NAME


def user_settings_path(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> Path:
    return user_config_directory(
        env,
        home=home,
        platform_name=platform_name,
    ) / SETTINGS_NAME


def crash_log_candidates(
    env: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    fallback_root: Path | None = None,
    platform_name: str | None = None,
) -> tuple[Path, ...]:
    primary = user_log_directory(
        env,
        home=home,
        platform_name=platform_name,
    ) / CRASH_LOG_NAME
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
    platform_name: str | None = None,
) -> Path | None:
    """Write diagnostics to a user-writable location without masking the crash."""
    for path in crash_log_candidates(
        env,
        home=home,
        fallback_root=fallback_root,
        platform_name=platform_name,
    ):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(details, encoding="utf-8")
        except OSError:
            continue
        return path
    return None
