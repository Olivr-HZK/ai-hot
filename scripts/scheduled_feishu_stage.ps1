$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$env:PYTHONIOENCODING = "utf-8"

$Python = "C:\Python314\python.exe"
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python).Source
}

$Hotspots = Join-Path $RepoRoot "skill_runs\hotspots.json"
if (-not (Test-Path $Hotspots)) {
    throw "Hotspots file not found: $Hotspots"
}
$HotspotsItem = Get-Item $Hotspots
if ($HotspotsItem.LastWriteTime -lt (Get-Date).Date) {
    throw "Hotspots file is stale: $Hotspots; last write time: $($HotspotsItem.LastWriteTime)"
}

$LogDir = Join-Path $RepoRoot "skill_runs\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "feishu_stage_$Stamp.log"

& $Python "scripts\feishu_push.py" "--hotspots" $Hotspots *>&1 | Tee-Object -FilePath $LogFile
exit $LASTEXITCODE
