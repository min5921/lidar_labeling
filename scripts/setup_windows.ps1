[CmdletBinding()]
param(
    [string]$EnvironmentDirectory = ".venv",
    [string]$PythonCommand = "",
    [switch]$Repair,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $EnvironmentDirectory))
$ProjectPrefix = $ProjectRoot.TrimEnd("\") + "\"
if (
    $EnvironmentRoot -eq $ProjectRoot -or
    -not $EnvironmentRoot.StartsWith(
        $ProjectPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "EnvironmentDirectory must resolve inside the project root: $EnvironmentRoot"
}
$EnvironmentPython = Join-Path $EnvironmentRoot "Scripts\python.exe"
$RuntimeLockPath = Join-Path $ProjectRoot "requirements-lock.txt"
$VerifierPath = Join-Path $ProjectRoot "scripts\verify_source_environment.py"
$DetectedCondaPrefix = $env:CONDA_PREFIX
$OriginalPathEntries = @($env:PATH -split ";")

# An activated Conda base commonly places incompatible Qt DLLs ahead of the
# locked PySide6 wheel. The source launcher uses an isolated venv, so retain
# only Windows system locations while setup and the application are running.
$env:PATH = @(
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem"),
    (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0")
) -join ";"
foreach ($VariableName in @(
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_PROMPT_MODIFIER",
    "CONDA_SHLVL",
    "PYTHONHOME",
    "PYTHONPATH",
    "QT_PLUGIN_PATH",
    "QML2_IMPORT_PATH"
)) {
    Remove-Item -LiteralPath "Env:$VariableName" -ErrorAction SilentlyContinue
}

if ($DetectedCondaPrefix) {
    Write-Host "[SETUP] Ignoring active Conda environment: $DetectedCondaPrefix"
}

function Test-CondaBasePython {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    & $Program @Arguments -c "import os, sys; root = os.path.normcase(sys.base_prefix); markers = ('anaconda', 'miniconda', 'miniforge', 'mambaforge'); is_conda = os.path.isdir(os.path.join(sys.base_prefix, 'conda-meta')) or any(marker in root for marker in markers); raise SystemExit(0 if is_conda else 1)"
    return $LASTEXITCODE -eq 0
}

function Test-PythonVersion {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    try {
        & $Program @Arguments -c "import os, struct, sys; root = os.path.normcase(sys.base_prefix); markers = ('anaconda', 'miniconda', 'miniforge', 'mambaforge'); is_conda = os.path.isdir(os.path.join(sys.base_prefix, 'conda-meta')) or any(marker in root for marker in markers); supported = sys.version_info >= (3, 10) and struct.calcsize('P') * 8 == 64 and not is_conda; raise SystemExit(0 if supported else 1)"
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function New-VenvWithPython {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    & $Program @Arguments -m venv $EnvironmentRoot
    if (
        $LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)
    ) {
        throw "Failed to create the project environment with $Program $Arguments."
    }
}

function New-ProjectEnvironment {
    if ($PythonCommand) {
        if (Test-CondaBasePython -Program $PythonCommand -Arguments @()) {
            throw "$PythonCommand is a Conda Python. Use an official python.org 64-bit Python 3.12 executable."
        }
        if (-not (Test-PythonVersion -Program $PythonCommand -Arguments @())) {
            throw "$PythonCommand is not 64-bit Python 3.10 or newer."
        }
        New-VenvWithPython -Program $PythonCommand -Arguments @()
        return
    }

    $LauncherCandidates = New-Object System.Collections.Generic.List[string]
    foreach ($Candidate in @(
        (Join-Path $env:LocalAppData "Programs\Python\Launcher\py.exe"),
        (Join-Path $env:SystemRoot "py.exe")
    )) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $LauncherCandidates.Add($Candidate)
        }
    }

    foreach ($Launcher in ($LauncherCandidates | Select-Object -Unique)) {
        # Python 3.12 is the primary clean-PC validation target. Fall back to
        # the newest installed supported Python when 3.12 is unavailable.
        if (Test-PythonVersion -Program $Launcher -Arguments @("-3.12")) {
            New-VenvWithPython -Program $Launcher -Arguments @("-3.12")
            return
        }
        if (Test-PythonVersion -Program $Launcher -Arguments @("-3")) {
            New-VenvWithPython -Program $Launcher -Arguments @("-3")
            return
        }
    }

    $PythonCandidates = New-Object System.Collections.Generic.List[string]
    foreach ($Candidate in @(
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        "C:\Python312\python.exe"
    )) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $PythonCandidates.Add($Candidate)
        }
    }
    foreach ($SearchRoot in @(
        (Join-Path $env:LocalAppData "Programs\Python"),
        $env:ProgramFiles
    )) {
        if (-not $SearchRoot -or -not (Test-Path -LiteralPath $SearchRoot)) {
            continue
        }
        Get-ChildItem -LiteralPath $SearchRoot -Directory -Filter "Python3*" |
            Sort-Object Name -Descending |
            ForEach-Object {
                $Candidate = Join-Path $_.FullName "python.exe"
                if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                    $PythonCandidates.Add($Candidate)
                }
            }
    }
    foreach ($Entry in $OriginalPathEntries) {
        $PathEntry = $Entry.Trim().Trim('"')
        if (-not $PathEntry) {
            continue
        }
        $Candidate = Join-Path $PathEntry "python.exe"
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $PythonCandidates.Add($Candidate)
        }
    }

    foreach ($Candidate in ($PythonCandidates | Select-Object -Unique)) {
        if (Test-PythonVersion -Program $Candidate -Arguments @()) {
            New-VenvWithPython -Program $Candidate -Arguments @()
            return
        }
    }

    throw "Official 64-bit CPython 3.10 or newer was not found. Conda Python cannot be used as the base of .venv. Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/ and run setup again."
}

function Remove-ProjectEnvironment {
    if (-not (Test-Path -LiteralPath $EnvironmentRoot)) {
        return
    }

    $ResolvedEnvironment = (Resolve-Path -LiteralPath $EnvironmentRoot).Path
    $EnvironmentItem = Get-Item -LiteralPath $ResolvedEnvironment -Force
    if (
        $ResolvedEnvironment -ne $EnvironmentRoot -or
        -not $ResolvedEnvironment.StartsWith(
            $ProjectPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Refusing to remove environment outside the project root: $ResolvedEnvironment"
    }
    if ($EnvironmentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to remove a linked environment: $ResolvedEnvironment"
    }

    Write-Host "[SETUP] Removing generated environment: $ResolvedEnvironment"
    Remove-Item -LiteralPath $ResolvedEnvironment -Recurse -Force
}

function Repair-LockedQtRuntime {
    $QtRequirements = @(
        Get-Content -LiteralPath $RuntimeLockPath |
            Where-Object {
                $_ -match '^(PySide6|PySide6_Addons|PySide6_Essentials|shiboken6)=='
            }
    )
    if ($QtRequirements.Count -ne 4) {
        throw "Expected four locked PySide6 runtime entries in $RuntimeLockPath."
    }

    Write-Host "[SETUP] Reinstalling the locked PySide6 native runtime..."
    $PipArguments = @(
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--force-reinstall"
    ) + $QtRequirements
    & $EnvironmentPython @PipArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to repair the locked PySide6 runtime."
    }
}

function Invoke-SourceEnvironmentVerification {
    & $EnvironmentPython $VerifierPath
}

Set-Location $ProjectRoot

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "LiDAR Label Tool requires 64-bit Windows."
}
$WindowsVersion = [Environment]::OSVersion.Version
if (
    $WindowsVersion.Major -lt 10 -or
    ($WindowsVersion.Major -eq 10 -and $WindowsVersion.Build -lt 17763)
) {
    throw "Qt 6.11 requires Windows 10 build 1809 or newer; found $WindowsVersion."
}

if ($Recreate) {
    Remove-ProjectEnvironment
}

if (-not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)) {
    New-ProjectEnvironment
}

if (Test-CondaBasePython -Program $EnvironmentPython -Arguments @()) {
    throw "The existing .venv was created from Conda Python. Install official 64-bit Python 3.12 and run setup_windows.bat -Recreate."
}

& $EnvironmentPython -c "import struct, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') * 8 == 64 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "$EnvironmentPython is not 64-bit Python 3.10 or newer. Run setup_windows.bat -Recreate."
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

$RepairAttempted = $false
if ($Repair) {
    Repair-LockedQtRuntime
    $RepairAttempted = $true
}

Invoke-SourceEnvironmentVerification
$VerificationExitCode = $LASTEXITCODE
if ($VerificationExitCode -ne 0) {
    if ($VerificationExitCode -eq 3 -and -not $RepairAttempted) {
        Write-Warning "Qt runtime verification failed; attempting one clean PySide6 repair."
        Repair-LockedQtRuntime
        Invoke-SourceEnvironmentVerification
        $VerificationExitCode = $LASTEXITCODE
    }

    if ($VerificationExitCode -eq 3) {
        Write-Host ""
        Write-Host "[ACTION] Try a completely new environment:"
        Write-Host "  launchers\windows\setup_windows.bat -Recreate"
        Write-Host "[ACTION] If the DLL error remains, install or repair the Microsoft Visual C++ x64 runtime:"
        Write-Host "  https://aka.ms/vc14/vc_redist.x64.exe"
        Write-Host "[ACTION] Confirm Windows 10 build 1809+ or Windows 11 x64 with winver."
        throw "Environment verification failed after PySide6 repair."
    }

    throw "Environment verification failed. Review the reported package/config mismatch."
}
