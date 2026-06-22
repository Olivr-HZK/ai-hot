$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$RunDailyScript = Join-Path $PSScriptRoot "scheduled_daily_full.ps1"
$RunTikTokKeywordScript = Join-Path $PSScriptRoot "scheduled_tiktok_keyword_discovery.ps1"

$DailyTaskName = "SocialMediaHotspots-Weekdays-0700-Full"
$InsKeywordTaskName = "SocialMediaHotspots-Daily-0001-InsKeywordDiscovery"
$TikTokKeywordTaskName = "SocialMediaHotspots-Daily-0001-TikTokKeywordDiscovery"
$ObsoleteTaskNames = @(
    "SocialMediaHotspots-20260522-0700-NoFeishu",
    "SocialMediaHotspots-20260522-0930-FeishuStage",
    $InsKeywordTaskName
)

foreach ($TaskName in $ObsoleteTaskNames) {
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
}

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

$DailyAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunDailyScript`"" `
    -WorkingDirectory $RepoRoot
$DailyTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At ([datetime]"2026-05-22 07:00:00")

Register-ScheduledTask `
    -TaskName $DailyTaskName `
    -Action $DailyAction `
    -Trigger $DailyTrigger `
    -Settings $Settings `
    -Description "Run the full social media daily pipeline at 07:00 on weekdays, including Feishu write/push." `
    -Force | Out-Null

$TikTokKeywordAction = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunTikTokKeywordScript`"" `
    -WorkingDirectory $RepoRoot
$TikTokKeywordTrigger = New-ScheduledTaskTrigger `
    -Daily `
    -At ([datetime]"2026-05-22 00:01:00")

Register-ScheduledTask `
    -TaskName $TikTokKeywordTaskName `
    -Action $TikTokKeywordAction `
    -Trigger $TikTokKeywordTrigger `
    -Settings $Settings `
    -Description "Run isolated TikTok cookie keyword discovery at 00:01; writes local reports only." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $DailyTaskName, $TikTokKeywordTaskName |
    Select-Object TaskName, State
