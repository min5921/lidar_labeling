[CmdletBinding()]
param(
    [string]$PythonCommand = "py",
    [string]$VenvDirectory = ".build\windows-portable-venv",
    [switch]$SkipTests,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPath = Join-Path $ProjectRoot $VenvDirectory
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Program $Arguments"
    }
}

function New-PortableVenv {
    param(
        [Parameter(Mandatory = $true)][string]$PythonCommand,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )
    if ($PythonCommand -eq "py") {
        & $PythonCommand @("-3.10", "-m", "venv", $TargetPath)
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Write-Host "Python 3.10 was not found by py launcher; trying the default Python 3 runtime."
        & $PythonCommand @("-3", "-m", "venv", $TargetPath)
        if ($LASTEXITCODE -eq 0) {
            return
        }
        throw "Could not create venv with py -3.10 or py -3"
    }
    Invoke-Checked -Program $PythonCommand -Arguments @("-m", "venv", $TargetPath)
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if ($SkipDependencyInstall) {
            throw "Cannot skip dependency installation because the build venv does not exist: $VenvPath"
        }
        New-PortableVenv -PythonCommand $PythonCommand -TargetPath $VenvPath
    }

    Invoke-Checked -Program $VenvPython -Arguments @(
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 'Python 3.10 or newer is required')"
    )
    if ($SkipDependencyInstall) {
        Invoke-Checked -Program $VenvPython -Arguments @(
            "-c", "import PyInstaller, PySide6, OpenGL, pyqtgraph"
        )
    }
    else {
        Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Checked -Program $VenvPython -Arguments @(
            "-m", "pip", "install", "-e", ".[gui,validation,dev,portable]"
        )
    }

    if (-not $SkipTests) {
        Invoke-Checked -Program $VenvPython -Arguments @("-m", "pytest")
        Invoke-Checked -Program $VenvPython -Arguments @("-m", "ruff", "check", ".")
    }

    $PyInstallerArguments = @(
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "LiDARLabelTool",
        "--distpath", (Join-Path $ProjectRoot "dist"),
        "--workpath", (Join-Path $ProjectRoot "build\pyinstaller"),
        "--specpath", (Join-Path $ProjectRoot "build"),
        "--collect-all", "pyqtgraph",
        "--collect-all", "OpenGL",
        "--add-data", "$((Join-Path $ProjectRoot "configs"));configs",
        "--add-data", "$((Join-Path $ProjectRoot "schemas"));schemas",
        "--add-data", "$((Join-Path $ProjectRoot "resources"));resources",
        (Join-Path $ProjectRoot "packaging\windows_entry.py")
    )
    Invoke-Checked -Program $VenvPython -Arguments (@("-m", "PyInstaller") + $PyInstallerArguments)

    $Executable = Join-Path $ProjectRoot "dist\LiDARLabelTool\LiDARLabelTool.exe"
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "Portable executable was not created: $Executable"
    }
    Write-Host "Portable build complete: $Executable"
}
finally {
    Pop-Location
}
