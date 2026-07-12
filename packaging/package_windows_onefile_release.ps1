[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReleaseName,
    [string]$Executable = "dist\LiDARLabelTool.exe",
    [string]$OutputDirectory = "release_packages"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($ReleaseName -notmatch '^[A-Za-z0-9._-]+$') {
    throw "ReleaseName may contain only letters, digits, '.', '_' and '-'."
}

$Source = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Executable))
$OutputRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputDirectory))
$Target = Join-Path $OutputRoot "$ReleaseName.exe"
$HashPath = Join-Path $OutputRoot "$ReleaseName.sha256.txt"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "One-file executable does not exist: $Source"
}
if ((Test-Path -LiteralPath $Target) -or (Test-Path -LiteralPath $HashPath)) {
    throw "Release output already exists: $ReleaseName"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
Copy-Item -LiteralPath $Source -Destination $Target
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Target).Hash
"$Hash  $ReleaseName.exe" | Set-Content -LiteralPath $HashPath -Encoding ascii

Write-Host "One-file release complete: $Target"
Write-Host "SHA-256: $Hash"
