[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReleaseName,
    [string]$DistDirectory = "dist\LiDARLabelTool",
    [string]$OutputDirectory = "release_packages",
    [string]$DefaultDatasetPath = "E:\one_chip_converted"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Path))
}

if ($ReleaseName -notmatch '^[A-Za-z0-9._-]+$') {
    throw "ReleaseName may contain only letters, digits, '.', '_' and '-'."
}

$DistPath = Get-ProjectPath $DistDirectory
$OutputRoot = Get-ProjectPath $OutputDirectory
$ReleasePath = Join-Path $OutputRoot $ReleaseName
$ZipPath = "$ReleasePath.zip"
$HashPath = "$ReleasePath.sha256.txt"
$TemplateRoot = Join-Path $PSScriptRoot "portable_bundle"

if (-not (Test-Path -LiteralPath (Join-Path $DistPath "LiDARLabelTool.exe"))) {
    throw "Portable build was not found: $DistPath"
}
foreach ($target in ($ReleasePath, $ZipPath, $HashPath)) {
    if (Test-Path -LiteralPath $target) {
        throw "Release output already exists: $target"
    }
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ReleasePath | Out-Null
Copy-Item -Path (Join-Path $DistPath "*") -Destination $ReleasePath -Recurse

$DatasetsPath = Join-Path $ReleasePath "datasets"
$ManualsPath = Join-Path $ReleasePath "manuals"
New-Item -ItemType Directory -Path $DatasetsPath | Out-Null
New-Item -ItemType Directory -Path $ManualsPath | Out-Null

Copy-Item -LiteralPath (Join-Path $TemplateRoot "Start_LiDAR_Label_Tool.bat") `
    -Destination (Join-Path $ReleasePath "Start_LiDAR_Label_Tool.bat")
Copy-Item -LiteralPath (Join-Path $TemplateRoot "README_DATASET_HERE.md") `
    -Destination (Join-Path $DatasetsPath "README_DATASET_HERE.md")

$ReadmeTemplate = Get-Content -Raw -LiteralPath (Join-Path $TemplateRoot "README_FIRST.md")
$Readme = $ReadmeTemplate.Replace("{{RELEASE_NAME}}", $ReleaseName).Replace(
    "{{DEFAULT_DATASET_PATH}}", $DefaultDatasetPath
)
Set-Content -LiteralPath (Join-Path $ReleasePath "README_FIRST.md") `
    -Value $Readme -Encoding UTF8

$LauncherTemplate = Get-Content -Raw -LiteralPath (
    Join-Path $TemplateRoot "Open_Configured_Dataset.bat"
)
$Launcher = $LauncherTemplate.Replace("{{DEFAULT_DATASET_PATH}}", $DefaultDatasetPath)
Set-Content -LiteralPath (Join-Path $ReleasePath "Open_Configured_Dataset.bat") `
    -Value $Launcher -Encoding ASCII

$ManualSources = @(
    @("docs\USER_MANUAL.md", "USER_MANUAL.md"),
    @("docs\18_PREFLIGHT_AND_QA.md", "PREFLIGHT_AND_QA.md"),
    @("docs\19_TRIAL_RUN_MANUAL.md", "TRIAL_RUN_MANUAL.md"),
    @("docs\20_ONE_CHIP_CONVERSION_MANUAL.md", "ONE_CHIP_CONVERSION_MANUAL.md"),
    @("docs\22_PORTABLE_DISTRIBUTION_CHECKLIST.md", "PORTABLE_QA_CHECKLIST.md")
)
foreach ($manual in $ManualSources) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $manual[0]) `
        -Destination (Join-Path $ManualsPath $manual[1])
}

$Branch = (& git -C $ProjectRoot branch --show-current 2>$null)
$Commit = (& git -C $ProjectRoot rev-parse HEAD 2>$null)
$Dirty = [bool](& git -C $ProjectRoot status --porcelain 2>$null)
$BuildInfo = @(
    "ReleaseName: $ReleaseName",
    "PackagedAtUtc: $([DateTime]::UtcNow.ToString('o'))",
    "GitBranch: $Branch",
    "GitCommit: $Commit",
    "WorkingTreeDirty: $Dirty",
    "Executable: LiDARLabelTool.exe",
    "RuntimeDirectory: _internal"
)
Set-Content -LiteralPath (Join-Path $ReleasePath "BUILD_INFO.txt") `
    -Value $BuildInfo -Encoding UTF8

Compress-Archive -LiteralPath $ReleasePath -DestinationPath $ZipPath -CompressionLevel Optimal
$Hash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
Set-Content -LiteralPath $HashPath `
    -Value "$($Hash.Hash)  $([System.IO.Path]::GetFileName($ZipPath))" -Encoding ASCII

Write-Host "Portable release folder: $ReleasePath"
Write-Host "Portable release ZIP:    $ZipPath"
Write-Host "SHA256:                 $($Hash.Hash)"
