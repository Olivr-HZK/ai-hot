$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogDir = Join-Path $RepoRoot "skill_runs\logs"
$LockDir = Join-Path $RepoRoot "skill_runs\locks"
$LockFile = Join-Path $LockDir "ins_keyword_discovery.lock"
$LogFile = Join-Path $LogDir "ins_keyword_discovery_$Stamp.log"

function Write-Log {
    param([string]$Message)
    $Message | Tee-Object -FilePath $LogFile -Append
}

function Test-EnvEnabled {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLowerInvariant()
}

New-Item -ItemType Directory -Force -Path $LogDir, $LockDir | Out-Null

if (-not (Test-EnvEnabled $env:INS_KEYWORD_DISCOVERY_DAILY_ENABLED)) {
    Write-Log "INS keyword discovery daily task disabled by INS_KEYWORD_DISCOVERY_DAILY_ENABLED"
    exit 0
}

try {
    $LockStream = [System.IO.File]::Open($LockFile, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $Writer = New-Object System.IO.StreamWriter($LockStream)
    $Writer.WriteLine("$PID $(Get-Date -Format o)")
    $Writer.Dispose()
} catch {
    Write-Log "INS keyword discovery already running; lock exists: $LockFile"
    exit 0
}

try {
    Set-Location $RepoRoot
    Write-Log "[$(Get-Date -Format o)] INS keyword discovery daily run started"
    Write-Log "Repo: $RepoRoot"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonBin "scripts\manual\ins_keyword_discovery.py" --max-pool-terms 0 2>&1 |
            ForEach-Object { $_.ToString() } |
            Tee-Object -FilePath $LogFile -Append
        $Code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($Code -ne 0) {
        throw "INS keyword discovery exited with code $Code"
    }
    Write-Log "[$(Get-Date -Format o)] INS keyword discovery daily run finished"
} finally {
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}
