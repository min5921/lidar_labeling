from __future__ import annotations

from importlib import metadata
from pathlib import Path
import re
import sys


LOCK_PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)$")


def locked_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"Unsupported lock entry: {line}")
        requirements[match.group("name")] = match.group("version")
    return requirements


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 10):
        print(
            f"[ERROR] Python 3.10 or newer is required; found {sys.version.split()[0]}.",
            file=sys.stderr,
        )
        return 2

    expected_packages = locked_requirements(
        project_root / "requirements-bootstrap-lock.txt"
    )
    expected_packages.update(
        locked_requirements(project_root / "requirements-lock.txt")
    )

    mismatches: list[str] = []
    for name, expected in expected_packages.items():
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{name}: {actual} (expected {expected})")

    try:
        from lidar_label_tool.app.config import default_config_path, load_config

        config_path = default_config_path()
        load_config(config_path)
    except (ImportError, OSError, ValueError) as exc:
        mismatches.append(f"lidar-label-tool/config: {type(exc).__name__}: {exc}")

    if mismatches:
        print("[ERROR] Source environment verification failed:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        return 2

    print(
        "[OK] LiDAR Label Tool source environment verified "
        f"(Python {sys.version.split()[0]}, {len(expected_packages)} locked packages)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
