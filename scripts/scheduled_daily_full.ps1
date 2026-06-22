$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$env:PYTHONIOENCODING = "utf-8"
$env:PIPELINE_PLATFORMS = "tiktok,x,ins"

$Python = "C:\Python314\python.exe"
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python).Source
}

$LogDir = Join-Path $RepoRoot "skill_runs\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "daily_full_$Stamp.log"

& $Python "run_pipeline.py" "--platforms" "tiktok,x,ins" *>&1 | Tee-Object -FilePath $LogFile
exit $LASTEXITCODE
