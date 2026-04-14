# scripts/setup-log-cleanup-task.ps1
# Windows Task Scheduler에 로그 정리 작업 등록
# 사용법: .\scripts\setup-log-cleanup-task.ps1 [-Time "01:00"] [-RetentionDays 3] [-Remove]
# 주의: 관리자 권한 필요
#
# 스케줄러 API 통합:
#   - Task 폴더: MonitorPage (기존 스케줄러 API와 동일)
#   - Task 이름: LogCleanup
#   - API 경로: GET /api/v1/scheduler/tasks/LogCleanup

param(
    [string]$TaskFolder = "MonitorPage",   # Task Scheduler 폴더 (스케줄러 API 통합)
    [string]$TaskName = "LogCleanup",      # Task 이름 (ALLOWED_TASKS에 등록됨)
    [string]$Time = "01:00",               # 실행 시간
    [int]$RetentionDays = 3,               # 보관 일수
    [switch]$Remove                        # 작업 제거
)

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires administrator privileges." -ForegroundColor Red
    Write-Host "Please run PowerShell as Administrator and try again."
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CleanupScript = Join-Path $ScriptDir "cleanup-logs.ps1"

# 스크립트 존재 확인
if (-not (Test-Path $CleanupScript)) {
    Write-Host "ERROR: cleanup-logs.ps1 not found at: $CleanupScript" -ForegroundColor Red
    exit 1
}

$TaskPath = "\$TaskFolder\"
$FullTaskName = "$TaskFolder\$TaskName"

if ($Remove) {
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
        Write-Host "Task '$FullTaskName' removed." -ForegroundColor Green
    } else {
        Write-Host "Task '$FullTaskName' not found."
    }
    exit 0
}

# 기존 작업 제거
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "Existing task removed."
}

# 작업 생성
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$CleanupScript`" -RetentionDays $RetentionDays"

$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "Monitor Page 로그 자동 정리 (${RetentionDays}일 보관)" | Out-Null

Write-Host ""
Write-Host "Task '$FullTaskName' registered successfully!" -ForegroundColor Green
Write-Host "  - Schedule: Daily at $Time"
Write-Host "  - Retention: $RetentionDays days"
Write-Host "  - Script: $CleanupScript"
Write-Host ""
Write-Host "To verify: Get-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath'"
Write-Host "To remove: .\scripts\setup-log-cleanup-task.ps1 -Remove"
Write-Host ""
Write-Host "API access: GET /api/v1/scheduler/tasks/$TaskName"
