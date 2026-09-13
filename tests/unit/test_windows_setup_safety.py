from __future__ import annotations

import base64
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="Windows setup safety requires a Windows PowerShell process",
)


def _powershell(command: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def _quote(path: Path | str) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _copy_setup(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "설치 검수 project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    setup = scripts / "setup_windows.ps1"
    shutil.copyfile(PROJECT_ROOT / "scripts" / setup.name, setup)
    return root, setup


@WINDOWS_ONLY
@pytest.mark.parametrize(
    "environment", ["src", "local_data", "configs", ".", "..", ".venv/../src"]
)
def test_recreate_refuses_non_environment_directories(
    tmp_path: Path, environment: str
) -> None:
    root, setup = _copy_setup(tmp_path)
    sentinel = root / "src" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("user source must survive", encoding="utf-8")

    result = _powershell(
        f"& {_quote(setup)} -EnvironmentDirectory {_quote(environment)} -Recreate"
    )

    assert result.returncode != 0
    assert "EnvironmentDirectory must be" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "user source must survive"


@WINDOWS_ONLY
def test_recreate_preserves_unrecognized_venv_folder(tmp_path: Path) -> None:
    root, setup = _copy_setup(tmp_path)
    sentinel = root / ".venv" / "keep.txt"
    sentinel.parent.mkdir()
    sentinel.write_text("not a generated environment", encoding="utf-8")

    result = _powershell(f"& {_quote(setup)} -Recreate")

    assert result.returncode != 0
    assert "Refusing to remove .venv without pyvenv.cfg" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "not a generated environment"


@WINDOWS_ONLY
def test_removal_function_accepts_only_recognized_environment(tmp_path: Path) -> None:
    # Extract only the deletion guard and mock the actual deletion. Never run pip
    # or create a real venv, and never delete even a test directory in this probe.
    root, setup = _copy_setup(tmp_path)
    environment = root / ".venv"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = example\n", encoding="utf-8")
    command = f"""
$ErrorActionPreference = 'Stop'
$ProjectRoot = {_quote(root)}
$ProjectPrefix = $ProjectRoot.TrimEnd('\') + '\'
$EnvironmentRoot = {_quote(environment)}
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_quote(setup)}, [ref]$null, [ref]$null
)
$functionAst = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Remove-ProjectEnvironment'
}}, $true)
function Remove-Item {{
    param([string]$LiteralPath, [switch]$Recurse, [switch]$Force)
    if ($LiteralPath -ne $EnvironmentRoot) {{ throw 'Unexpected deletion target' }}
    Write-Output 'MOCK_ENVIRONMENT_REMOVAL'
}}
Invoke-Expression $functionAst.Extent.Text
Remove-ProjectEnvironment
"""

    result = _powershell(command)

    assert result.returncode == 0, result.stderr
    assert "MOCK_ENVIRONMENT_REMOVAL" in result.stdout
    assert (environment / "pyvenv.cfg").is_file()


def test_ci_covers_active_branch_supported_pythons_and_type_checks() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/test-source-environments.yml").read_text(
        encoding="utf-8"
    )
    assert "- codex/v2" in workflow
    assert "- windows-2022" in workflow
    assert "- ubuntu-22.04" in workflow
    assert '- "3.10"' in workflow
    assert '- "3.12"' in workflow
    assert "python-version: ${{ matrix.python }}" in workflow
    assert "python -m mypy src" in workflow
    dev_lock = (PROJECT_ROOT / "requirements-dev-lock.txt").read_text(encoding="utf-8")
    assert "mypy==" in dev_lock
    assert 'tomli==2.4.1; python_version < "3.11"' in dev_lock
