param(
    [string]$Platforms = "tiktok,x,ins"
)

$ErrorActionPreference = "Stop"

$ScriptPath = $MyInvocation.MyCommand.Path
$ScriptsDir = Split-Path -Parent $ScriptPath
$ProjectRoot = Split-Path -Parent $ScriptsDir
$LogDir = Join-Path $ProjectRoot "skill_runs\scheduled_runs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogDir "pipeline_$Stamp.log"
$Python = "C:\Python314\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Set-Location $ProjectRoot

function Write-Log {
    param([string]$Message)
    Add-Content -Path $LogPath -Value $Message -Encoding UTF8
}

$ExitCode = 1
try {
    Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting scheduled pipeline"
    Write-Log "ProjectRoot=$ProjectRoot"
    Write-Log "Platforms=$Platforms"
    Write-Log "Python=$Python"

    $PipelineArgs = @("run_pipeline.py", "--platforms", $Platforms)
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python @PipelineArgs >> $LogPath 2>&1
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($null -eq $ExitCode) {
        $ExitCode = 0
    }
} catch {
    Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Scheduled pipeline wrapper failed: $($_.Exception.Message)"
    $ExitCode = 1
}

Write-Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline finished with exit code $ExitCode"
exit $ExitCode
