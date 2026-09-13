from __future__ import annotations

from email.message import Message
import hashlib
from importlib import metadata
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.collect_third_party_licenses import collect_licenses, main, read_locks


class FakeDistribution(metadata.Distribution):
    def __init__(
        self, root: Path, *, version: str = "1.2.3", files: list[str] | None = None,
        fields: list[tuple[str, str]] | None = None,
    ) -> None:
        self.root = root
        self._version = version
        self._files = files
        self._message = Message()
        for key, value in fields or []:
            self._message[key] = value

    @property
    def version(self) -> str:
        return self._version

    @property
    def metadata(self) -> Message:
        return self._message

    @property
    def files(self) -> list[metadata.PackagePath] | None:
        return None if self._files is None else [metadata.PackagePath(item) for item in self._files]

    def locate_file(self, path: object) -> Path:
        return self.root / str(path)

    def read_text(self, filename: str) -> str | None:
        return None


def _environment(tmp_path: Path) -> tuple[Path, FakeDistribution, bytes]:
    lock = tmp_path / "requirements-lock.txt"
    lock.write_text("Demo_Package==1.2.3\n", encoding="utf-8")
    root = tmp_path / "site-packages"
    source = root / "demo_package-1.2.3.dist-info/licenses/LICENSE"
    source.parent.mkdir(parents=True)
    original = b"Original license\r\nBytes \xff must be preserved\r\n"
    source.write_bytes(original)
    dist = FakeDistribution(root, files=[source.relative_to(root).as_posix()], fields=[
        ("License-Expression", "MIT"), ("License-File", "LICENSE"),
    ])
    return lock, dist, original


def test_collects_original_bytes_and_reproducible_manifest(tmp_path: Path) -> None:
    lock, dist, original = _environment(tmp_path)
    first = tmp_path / "결과 한글" / "first"
    second = tmp_path / "second"
    def lookup(name: str) -> FakeDistribution:
        return dist
    manifest = collect_licenses(first, [lock], distribution_lookup=lookup)
    collect_licenses(second, [lock], distribution_lookup=lookup)
    assert manifest["error_count"] == manifest["warning_count"] == 0
    assert manifest["legal_review_required"] is True
    item = manifest["packages"][0]["files"][0]
    assert (first / item["output_path"]).read_bytes() == original
    assert item["sha256"] == hashlib.sha256(original).hexdigest()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert str(tmp_path) not in (first / "manifest.json").read_text(encoding="utf-8")
    assert (first / manifest["locks"][0]["output_path"]).read_bytes() == lock.read_bytes()
    assert dist.locate_file(dist.files[0]).read_bytes() == original


def test_missing_mismatched_unknown_and_declared_missing_are_reported(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    lock.write_text("Demo_Package==9.9\nmissing==1.0\n", encoding="utf-8")
    dist = FakeDistribution(dist.root, files=[], fields=[("License", "UNKNOWN"),
                                                       ("License-File", "MISSING.txt")])

    def lookup(name: str) -> FakeDistribution:
        if name == "missing":
            raise metadata.PackageNotFoundError(name)
        return dist

    manifest = collect_licenses(tmp_path / "result", [lock], distribution_lookup=lookup)
    codes = {issue["code"] for issue in manifest["issues"]}
    assert {"package_missing", "version_mismatch", "license_metadata_unknown",
            "license_files_missing", "declared_license_missing"} <= codes
    assert manifest["error_count"] == 2
    assert manifest["packages"][0]["installed_version"] == "1.2.3"


def test_declared_custom_license_name_is_collected(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    custom = dist.root / "demo/legal_terms.txt"
    custom.parent.mkdir()
    custom.write_bytes(b"Custom terms")
    dist = FakeDistribution(dist.root, files=["demo/legal_terms.txt"], fields=[
        ("License", "LicenseRef-Proprietary OR MIT"), ("License-File", "legal_terms.txt"),
    ])
    manifest = collect_licenses(tmp_path / "result", [lock], distribution_lookup=lambda name: dist)
    assert manifest["notice_file_count"] == 1
    assert {issue["code"] for issue in manifest["issues"]} == {"license_choice_review"}


def test_no_package_import_or_out_of_scope_distribution_lookup(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    names = []

    def lookup(name: str) -> FakeDistribution:
        names.append(name)
        return dist

    with patch("importlib.import_module", side_effect=AssertionError("no package imports")):
        collect_licenses(tmp_path / "result", [lock], distribution_lookup=lookup)
    assert names == ["Demo_Package"]


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_existing_output_is_preserved_without_metadata_reads(tmp_path: Path, kind: str) -> None:
    output = tmp_path / "existing"
    if kind == "file":
        output.write_bytes(b"old")
    else:
        output.mkdir()
        (output / "old").write_bytes(b"old")
    with pytest.raises(FileExistsError):
        collect_licenses(output, [tmp_path / "does-not-exist.lock"])
    assert (output if kind == "file" else output / "old").read_bytes() == b"old"


def test_lock_includes_markers_duplicates_and_cycle_validation(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.txt"
    runtime.write_text("demo==1.0\n", encoding="utf-8")
    dev = tmp_path / "dev.txt"
    dev.write_text('-r runtime.txt\nDemo==1.0\nskipped==1.0; python_version < "1.0"\n', encoding="utf-8")
    requirements, snapshots = read_locks([dev, runtime])
    assert requirements == {"demo": ("demo", "1.0")}
    assert len(snapshots) == 2
    runtime.write_text("-r dev.txt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cyclic"):
        read_locks([dev])


@pytest.mark.parametrize("line", ["demo>=1.0", "--extra-index-url https://invalid",
                                     '-r ../outside.txt', 'demo==1.0; unknown == "yes"',
                                     "demo==1.0\ndemo==2.0"])
def test_unsupported_lock_never_creates_output(tmp_path: Path, line: str) -> None:
    lock = tmp_path / "lock.txt"
    lock.write_text(line, encoding="utf-8")
    output = tmp_path / "result"
    with pytest.raises(ValueError):
        collect_licenses(output, [lock])
    assert not output.exists()


def test_unsafe_notice_paths_are_not_read_or_copied(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    private = tmp_path / "LICENSE.private"
    private.write_bytes(b"private content")
    dist = FakeDistribution(dist.root, files=["../LICENSE.private", str(private)], fields=[
        ("License", "MIT"), ("License-File", "../LICENSE.private"),
    ])
    output = tmp_path / "result"
    manifest = collect_licenses(output, [lock], distribution_lookup=lambda name: dist)
    assert manifest["error_count"] == 3
    assert manifest["notice_file_count"] == 0
    result_bytes = (output / "manifest.json").read_bytes()
    assert b"private content" not in result_bytes
    # Declared metadata itself is preserved verbatim; absolute installed paths
    # rejected from RECORD do not appear in the public file/error inventory.
    assert str(private) not in result_bytes.decode("utf-8")


def test_missing_inventory_and_files_are_visible(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    without_inventory = FakeDistribution(dist.root, files=None)
    result = collect_licenses(tmp_path / "first", [lock], distribution_lookup=lambda name: without_inventory)
    assert "file_inventory_missing" in {item["code"] for item in result["issues"]}
    missing_file = FakeDistribution(dist.root, files=["LICENSE.missing"])
    result = collect_licenses(tmp_path / "second", [lock], distribution_lookup=lambda name: missing_file)
    assert "notice_unreadable" in {item["code"] for item in result["issues"]}


def test_bundled_notices_are_collected_but_not_treated_as_primary_license(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    notice = dist.root / "demo/native/freeglut_COPYING.txt"
    notice.parent.mkdir(parents=True)
    notice.write_bytes(b"Native dependency notice")
    dist = FakeDistribution(dist.root, files=[notice.relative_to(dist.root).as_posix()],
                            fields=[("License", "BSD")])
    result = collect_licenses(tmp_path / "result", [lock], distribution_lookup=lambda name: dist)
    assert result["notice_file_count"] == 1
    assert {item["code"] for item in result["issues"]} == {"primary_license_document_review"}


def test_failed_manifest_publication_leaves_no_completion_marker_or_overwrite(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    output = tmp_path / "result"
    with patch("scripts.collect_third_party_licenses.os.link", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            collect_licenses(output, [lock], distribution_lookup=lambda name: dist)
    assert output.is_dir()  # New artifacts retained for manual inspection.
    assert not (output / "manifest.json").exists()
    assert not tuple(output.glob(".*.tmp"))
    with pytest.raises(FileExistsError):
        collect_licenses(output, [lock], distribution_lookup=lambda name: dist)


def test_cli_reports_collection_error_without_traceback(tmp_path: Path) -> None:
    assert main(["--output", str(tmp_path / "new"), "--lock", str(tmp_path / "missing.txt")]) == 2
    assert not (tmp_path / "new").exists()


def test_manifest_is_valid_json_and_completion_is_exclusive(tmp_path: Path) -> None:
    lock, dist, _ = _environment(tmp_path)
    output = tmp_path / "result"
    real_link = __import__("os").link

    def racing_link(source: Path, target: Path) -> None:
        target.write_bytes(b"other writer")
        real_link(source, target)

    with patch("scripts.collect_third_party_licenses.os.link", racing_link):
        with pytest.raises(FileExistsError):
            collect_licenses(output, [lock], distribution_lookup=lambda name: dist)
    assert (output / "manifest.json").read_bytes() == b"other writer"
    assert not tuple(output.glob(".*.tmp"))
    other = tmp_path / "other"
    result = collect_licenses(other, [lock], distribution_lookup=lambda name: dist)
    assert json.loads((other / "manifest.json").read_text(encoding="utf-8")) == result
