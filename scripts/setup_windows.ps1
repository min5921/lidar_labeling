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

function Test-PythonVersion {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    try {
        & $Program @Arguments -c "import struct, sys; raise SystemExit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') * 8 == 64 else 1)"
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
        if (-not (Test-PythonVersion -Program $PythonCommand -Arguments @())) {
            throw "$PythonCommand is not 64-bit Python 3.10 or newer."
        }
        New-VenvWithPython -Program $PythonCommand -Arguments @()
        return
    }

    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        # Python 3.12 is the primary clean-PC validation target. Fall back to
        # the newest installed supported Python when 3.12 is unavailable.
        if (Test-PythonVersion -Program "py.exe" -Arguments @("-3.12")) {
            New-VenvWithPython -Program "py.exe" -Arguments @("-3.12")
            return
        }
        if (Test-PythonVersion -Program "py.exe" -Arguments @("-3")) {
            New-VenvWithPython -Program "py.exe" -Arguments @("-3")
            return
        }
    }

    if (
        (Get-Command python.exe -ErrorAction SilentlyContinue) -and
        (Test-PythonVersion -Program "python.exe" -Arguments @())
    ) {
        New-VenvWithPython -Program "python.exe" -Arguments @()
        return
    }

    throw "64-bit Python 3.10 or newer was not found. Install 64-bit Python 3.12 and run launchers\windows\setup_windows.bat again."
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
