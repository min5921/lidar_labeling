[CmdletBinding()]
param(
    [string]$EnvironmentDirectory = ".venv",
    [string]$PythonCommand = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentRoot = Join-Path $ProjectRoot $EnvironmentDirectory
$EnvironmentPython = Join-Path $EnvironmentRoot "Scripts\python.exe"

function Test-PythonVersion {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    try {
        & $Program @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function New-ProjectEnvironment {
    if ($PythonCommand) {
        if (-not (Test-PythonVersion -Program $PythonCommand -Arguments @())) {
            throw "$PythonCommand is not Python 3.10 or newer."
        }
        & $PythonCommand -m venv $EnvironmentRoot
        return
    }

    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        if (Test-PythonVersion -Program "py.exe" -Arguments @("-3.10")) {
            & py.exe -3.10 -m venv $EnvironmentRoot
            return
        }
        if (Test-PythonVersion -Program "py.exe" -Arguments @("-3")) {
            & py.exe -3 -m venv $EnvironmentRoot
            return
        }
    }

    if (
        (Get-Command python.exe -ErrorAction SilentlyContinue) -and
        (Test-PythonVersion -Program "python.exe" -Arguments @())
    ) {
        & python.exe -m venv $EnvironmentRoot
        return
    }

    throw "Python 3.10 or newer was not found. Install Python and run setup_windows.bat again."
}

Set-Location $ProjectRoot

if (-not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)) {
    New-ProjectEnvironment
}

& $EnvironmentPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "$EnvironmentPython is older than Python 3.10. Remove .venv and run setup again."
}

& $EnvironmentPython -m pip install --requirement requirements-bootstrap-lock.txt
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install locked pip, setuptools, and wheel."
}

& $EnvironmentPython -m pip install --requirement requirements-lock.txt
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install locked runtime dependencies."
}

& $EnvironmentPython -m pip install --no-build-isolation --no-deps --editable .
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install LiDAR Label Tool."
}

& $EnvironmentPython scripts\verify_source_environment.py
if ($LASTEXITCODE -ne 0) {
    throw "Environment verification failed."
}
