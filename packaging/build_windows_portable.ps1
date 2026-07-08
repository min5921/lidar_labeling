[CmdletBinding()]
param(
    [string]$PythonCommand = "py",
    [string]$VenvDirectory = ".build\windows-portable-venv",
    [switch]$SkipTests
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

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if ($PythonCommand -eq "py") {
            Invoke-Checked -Program $PythonCommand -Arguments @("-3.10", "-m", "venv", $VenvPath)
        }
        else {
            Invoke-Checked -Program $PythonCommand -Arguments @("-m", "venv", $VenvPath)
        }
    }

    Invoke-Checked -Program $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -Program $VenvPython -Arguments @(
        "-m", "pip", "install", "-e", ".[gui,validation,dev,portable]"
    )

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
        "--add-data", "configs;configs",
        "--add-data", "schemas;schemas",
        "--add-data", "resources;resources",
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
