$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogDir = Join-Path $RepoRoot "skill_runs\logs"
$LogFile = Join-Path $LogDir "tiktok_keyword_discovery_$Stamp.log"
$RootEnvFile = Join-Path $RepoRoot ".env"

function Write-Log {
    param([string]$Message)
    $Message | Tee-Object -FilePath $LogFile -Append
}

function Import-RootEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $Line = $_.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            return
        }
        $Parts = $Line.Split("=", 2)
        $Key = $Parts[0].Trim()
        $Value = $Parts[1].Trim()
        if (-not $Key) {
            return
        }
        if (($Value.Length -ge 2) -and (($Value[0] -eq "'" -and $Value[$Value.Length - 1] -eq "'") -or ($Value[0] -eq '"' -and $Value[$Value.Length - 1] -eq '"'))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        [System.Environment]::SetEnvironmentVariable($Key, $Value, "Process")
    }
}

function Test-EnvEnabled {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLowerInvariant()
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Import-RootEnv $RootEnvFile
Write-Log "Loaded root env: $RootEnvFile"

if (-not (Test-EnvEnabled $env:TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED)) {
    Write-Log "TikTok keyword discovery daily task disabled by TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED"
    exit 0
}

try {
    Set-Location $RepoRoot
    Write-Log "[$(Get-Date -Format o)] TikTok keyword discovery daily run started"
    Write-Log "Repo: $RepoRoot"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonBin "scripts\tiktok_keyword_discovery.py" 2>&1 |
            ForEach-Object { $_.ToString() } |
            Tee-Object -FilePath $LogFile -Append
        $Code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($Code -ne 0) {
        throw "TikTok keyword discovery exited with code $Code"
    }
    Write-Log "[$(Get-Date -Format o)] TikTok keyword discovery daily run finished"
} catch {
    Write-Log "[$(Get-Date -Format o)] TikTok keyword discovery failed: $($_.Exception.Message)"
    exit 1
}
