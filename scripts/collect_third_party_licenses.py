"""Read installed distribution metadata and collect notices without importing packages."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sys
from typing import Any
from uuid import uuid4


_LOCK_ENTRY = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9!+_.-]*)")
_PYTHON_MARKER = re.compile(r'''python_version\s*(<|<=|==|!=|>=|>)\s*["'](\d+\.\d+)["']''')
_NOTICE_STARTS = ("license", "licence", "copying", "notice", "copyright")
_NOTICE_FOLDERS = frozenset({"licenses", "licences", "license", "licence"})
_UNKNOWN = frozenset({"", "unknown", "none", "n/a", "noassertion"})


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _marker_applies(marker: str) -> bool:
    match = _PYTHON_MARKER.fullmatch(marker.strip())
    if match is None:
        raise ValueError(f"unsupported lock marker (not evaluated): {marker}")
    version = tuple(int(part) for part in match.group(2).split("."))
    current = sys.version_info[:2]
    return {
        "<": current < version, "<=": current <= version, "==": current == version,
        "!=": current != version, ">=": current >= version, ">": current > version,
    }[match.group(1)]


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or ":" in str(path):
        raise ValueError(f"unsafe metadata path: {value}")
    return path


def _is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points on supported Python versions."""
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def read_locks(paths: Sequence[Path]) -> tuple[dict[str, tuple[str, str]], list[tuple[str, bytes]]]:
    """Read exact pins and the current development lock's Python-version marker.

    Includes stay inside their declaring lock folder. Unknown pip options, loose
    pins, arbitrary marker expressions and conflicting pins are rejected.
    """
    requirements: dict[str, tuple[str, str]] = {}
    snapshots: list[tuple[str, bytes]] = []
    visited: set[Path] = set()
    active: set[Path] = set()

    def visit(requested: Path) -> None:
        path = requested.resolve()
        if path in active:
            raise ValueError(f"cyclic lock include: {path.name}")
        if path in visited:
            return
        active.add(path)
        content = path.read_bytes()
        snapshots.append((path.name, content))
        for raw_line in content.decode("utf-8-sig").splitlines():
            line = raw_line.split(" #", 1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                relative = _safe_relative(line[3:].strip())
                include = path.parent.joinpath(*relative.parts).resolve()
                if not include.is_relative_to(path.parent):
                    raise ValueError("lock include escapes its folder")
                visit(include)
                continue
            requirement, separator, marker = line.partition(";")
            match = _LOCK_ENTRY.fullmatch(requirement.strip())
            if match is None:
                raise ValueError(f"unsupported lock entry: {line}")
            if separator and not _marker_applies(marker):
                continue
            name, version = match.groups()
            key = _canonical_name(name)
            if key in requirements and requirements[key][1] != version:
                raise ValueError(f"conflicting locked versions for {name}")
            requirements.setdefault(key, (name, version))
        active.remove(path)
        visited.add(path)

    for path in paths:
        visit(Path(path))
    if not requirements:
        raise ValueError("lock files contain no packages for this interpreter")
    return requirements, snapshots


def _is_notice(path: PurePosixPath) -> bool:
    if any(part.casefold() in _NOTICE_FOLDERS for part in path.parts[:-1]):
        return True
    name = path.name.casefold()
    has_notice_name = name.startswith(_NOTICE_STARTS) or re.search(
        r"[._-](license|licence|copying|notice|copyright)", name
    ) is not None
    return has_notice_name and path.suffix.casefold() not in {
        ".py", ".pyc", ".pyd", ".dll", ".so", ".exe"
    }


def _json_bytes(document: Any) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n").encode("utf-8")


def _collect_distribution(
    name: str,
    expected: str,
    lookup: Callable[[str], metadata.Distribution],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    key = _canonical_name(name)
    record: dict[str, Any] = {
        "name": key, "requested_name": name, "expected_version": expected,
        "installed_version": None, "status": "missing", "files": [], "issues": [],
    }
    contents: dict[str, bytes] = {}

    def issue(code: str, message: str, severity: str = "warning") -> None:
        record["issues"].append({"code": code, "message": message, "severity": severity})

    try:
        dist = lookup(name)
    except metadata.PackageNotFoundError:
        issue("package_missing", "고정 package가 현재 환경에 설치되어 있지 않습니다.", "error")
        return record, contents
    version = dist.version
    record["installed_version"] = version
    record["status"] = "matched" if version == expected else "version_mismatch"
    if version != expected:
        issue("version_mismatch", "설치 버전이 lock과 다릅니다. 배포 환경을 다시 확인하세요.", "error")
    info = dist.metadata

    def header(name: str) -> str | None:
        values = info.get_all(name, [])
        return str(values[0]) if values else None

    expression = header("License-Expression")
    text_license = header("License")
    classifiers = sorted(value for value in info.get_all("Classifier", [])
                         if value.startswith("License ::"))
    declared = sorted(info.get_all("License-File", []))
    record["license_metadata"] = {
        "expression": expression, "text": text_license, "classifiers": classifiers,
        "declared_files": declared, "project_urls": sorted(info.get_all("Project-URL", [])),
        "home_page": header("Home-page"),
    }
    values = [str(expression or ""), str(text_license or ""), *classifiers]
    if not any(value.strip().casefold() not in _UNKNOWN for value in values):
        issue("license_metadata_unknown", "license 선언이 없거나 Unknown입니다. 원문을 검토하세요.")
    # A wheel's alternatives/reference token do not establish which terms the
    # distributor selected, nor whether all native component notices are present.
    if any(token in " ".join(values) for token in (" OR ", "LicenseRef-")):
        issue("license_choice_review", "대안/참조 license 선언은 적용 조건과 원문을 별도로 검토하세요.")
    base = Path(str(dist.locate_file(""))).resolve()
    candidates = dist.files
    if candidates is None:
        issue("file_inventory_missing", "distribution 파일 목록이 없어 notice를 확인할 수 없습니다.")
        candidates = []
    declared_paths: set[str] = set()
    for declaration in declared:
        try:
            declared_paths.add(_safe_relative(declaration).as_posix())
        except ValueError:
            issue("declared_license_unsafe", "License-File 선언에 안전하지 않은 경로가 있습니다.", "error")
    seen: set[str] = set()
    for package_path in sorted(candidates, key=lambda value: str(value).casefold()):
        relative_text = str(package_path).replace("\\", "/")
        declared_notice = any(relative_text == name or relative_text.endswith("/" + name)
                              for name in declared_paths)
        if not _is_notice(PurePosixPath(relative_text)) and not declared_notice:
            continue
        display_path = "<unsafe path>"
        try:
            relative = _safe_relative(relative_text)
            display_path = relative.as_posix()
            if display_path.casefold() in seen:
                raise ValueError("duplicate/case-fold collision in notice paths")
            seen.add(display_path.casefold())
            source = Path(str(dist.locate_file(package_path))).resolve()
            if not source.is_relative_to(base):
                raise ValueError("notice symlink escapes the distribution root")
            content = source.read_bytes()
        except (OSError, ValueError) as exc:
            # Never copy an absolute path/user home into the public manifest.
            issue("notice_unreadable", f"notice를 읽지 못했습니다: {display_path} ({type(exc).__name__})",
                  "error")
            continue
        destination = f"packages/{key}/files/{relative.as_posix()}"
        contents[destination] = content
        record["files"].append({
            "source_path": relative.as_posix(), "output_path": destination,
            "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content),
        })
    if not record["files"]:
        issue("license_files_missing", "설치 파일 목록에서 license/notice 원문을 찾지 못했습니다.")
    source_paths = [item["source_path"] for item in record["files"]]
    if source_paths and not any(
        ".dist-info/" in path and "/" not in path.split(".dist-info/", 1)[0]
        or len(PurePosixPath(path).parts) <= 2
        for path in source_paths
    ):
        issue("primary_license_document_review",
              "하위 bundled notice만 발견되었습니다. package 자체 license 원문을 별도로 확인하세요.")
    for declaration_relative in sorted(declared_paths):
        if not any(path == declaration_relative or path.endswith("/" + declaration_relative)
                   for path in source_paths):
            issue("declared_license_missing", f"선언된 License-File 원문이 없습니다: {declaration_relative}")
    contents[f"packages/{key}/license-metadata.json"] = _json_bytes(record["license_metadata"])
    return record, contents


def collect_licenses(
    output: Path,
    lock_paths: Sequence[Path],
    *,
    distribution_lookup: Callable[[str], metadata.Distribution] = metadata.distribution,
) -> dict[str, Any]:
    """Collect into a new directory; manifest.json is the completion marker.

    Existing output is never reused or replaced. If writing fails, an incomplete
    new directory may remain without a manifest; it is preserved for inspection,
    not recursively deleted. Retry with a different new output path.
    """
    target = Path(os.path.abspath(output))
    if target.exists() or _is_link(target):
        raise FileExistsError(f"기존 출력은 덮어쓰지 않습니다: {target}")
    if any(_is_link(parent) for parent in target.parents):
        raise ValueError("license output must not traverse symbolic-link directories")
    requirements, snapshots = read_locks(lock_paths)
    packages: list[dict[str, Any]] = []
    contents: dict[str, bytes] = {}
    for key in sorted(requirements):
        name, expected = requirements[key]
        record, notices = _collect_distribution(name, expected, distribution_lookup)
        packages.append(record)
        contents.update(notices)
    locks: list[dict[str, str]] = []
    for ordinal, (name, content) in enumerate(snapshots):
        destination = f"locks/{ordinal:03d}-{name}"
        contents[destination] = content
        locks.append({"name": name, "output_path": destination,
                      "sha256": hashlib.sha256(content).hexdigest()})
    issues = [{"package": item["name"], **issue} for item in packages for issue in item["issues"]]
    manifest: dict[str, Any] = {
        "schema_version": "1.0", "collector": "collect_third_party_licenses",
        "environment": {"python": platform.python_version(), "platform": sys.platform,
                        "implementation": platform.python_implementation(), "machine": platform.machine()},
        "scope": "installed distributions pinned by the supplied lock files",
        "legal_review_required": True,
        "limitations": [
            "수집 성공은 license 준수 또는 재배포 허가 판정이 아닙니다.",
            "Python 인터프리터·OS/GPU/VC++ runtime 및 감지되지 않은 bundled native 구성요소는 별도 점검합니다.",
            "코드 서명, 원본 source 제공 의무, 선택한 license 대안은 자동 판단하지 않습니다.",
        ],
        "locks": locks, "packages": packages, "issues": issues,
        "package_count": len(packages), "notice_file_count": sum(len(item["files"]) for item in packages),
        "error_count": sum(item["severity"] == "error" for item in issues),
        "warning_count": sum(item["severity"] == "warning" for item in issues),
    }
    contents["README.txt"] = (
        "이 폴더는 현재 lock과 설치 distribution의 license/notice 원본을 모은 검토 자료입니다.\n"
        "manifest.json이 있어야 수집이 완료된 것입니다. 라이선스 준수·서명 완료 증명은 아닙니다.\n"
        "설치 파일 원문은 수정 없이 복사하고 SHA-256을 manifest에 기록했습니다.\n"
    ).encode("utf-8")
    # Complete all metadata reads/preflight before touching the output. Exclusive
    # directory/file creation also preserves a concurrent writer's output.
    target.mkdir(parents=True, exist_ok=False)
    for relative, content in sorted(contents.items()):
        output_file = target.joinpath(*_safe_relative(relative).parts)
        if any(_is_link(parent) for parent in output_file.parents):
            raise ValueError("license output directory changed to a symbolic link")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    temporary = target / f".manifest-{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(_json_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target / "manifest.json")
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="설치된 고정 dependency의 license 검토 자료 수집")
    parser.add_argument("--output", required=True, type=Path, help="아직 존재하지 않는 출력 폴더")
    parser.add_argument("--lock", action="append", type=Path, help="별도 exact-pin lock (여러 번 가능)")
    parser.add_argument("--include-bootstrap", action="store_true", help="pip/setuptools/wheel도 포함")
    parser.add_argument("--include-dev", action="store_true", help="검증 도구 development lock도 포함")
    args = parser.parse_args(argv)
    locks = list(args.lock or [project_root / "requirements-lock.txt"])
    if args.include_bootstrap:
        locks.append(project_root / "requirements-bootstrap-lock.txt")
    if args.include_dev:
        locks.append(project_root / "requirements-dev-lock.txt")
    try:
        manifest = collect_licenses(args.output, locks)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] license 수집 실패: {exc}", file=sys.stderr)
        return 2
    print(f"{manifest['package_count']} packages, {manifest['notice_file_count']} notice files; "
          f"errors={manifest['error_count']}, warnings={manifest['warning_count']}")
    print(f"검토 자료: {args.output / 'manifest.json'} (법적 준수/코드 서명 판정 아님)")
    return 2 if manifest["error_count"] else (1 if manifest["warning_count"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
