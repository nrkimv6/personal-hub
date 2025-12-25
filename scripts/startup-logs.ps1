# Monitor Page - Startup Log Viewer
# Windows 부팅 후 서비스 로그 창을 자동으로 엽니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# Windows Terminal: 2탭 (운영 탭, 개발 탭)
# - 각 탭에 Service Runner 로그 + NSSM stdout/stderr

param(
    [int]$Delay = 15  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"
$LogDirDev = Join-Path $ProjectRoot "logs\dev"

# 서비스가 시작될 때까지 대기
Start-Sleep -Seconds $Delay

# 로그 파일 경로
# Production
$prodRunnerLog = Join-Path $LogDir "service_runner.log"
$prodNssmLog = Join-Path $LogDir "service_MonitorPage.log"
$prodNssmErrLog = Join-Path $LogDir "service_MonitorPage_err.log"

# Development
$devRunnerLog = Join-Path $LogDirDev "service_runner.log"
$devNssmLog = Join-Path $LogDirDev "service_MonitorPage-Dev.log"
$devNssmErrLog = Join-Path $LogDirDev "service_MonitorPage-Dev_err.log"

# 파일 대기 + tail 명령어 생성 함수
function Get-TailCommand {
    param([string]$LogFile, [string]$Label, [string]$Color)
    @"
Write-Host '$Label' -ForegroundColor $Color
Write-Host 'Log: $LogFile' -ForegroundColor Gray
if (-not (Test-Path '$LogFile')) {
    Write-Host 'Waiting for log file...' -ForegroundColor Yellow
    while (-not (Test-Path '$LogFile')) { Start-Sleep -Seconds 1 }
}
Get-Content '$LogFile' -Wait -Tail 100 -Encoding UTF8
"@
}

# Windows Terminal 확인
$wt = Get-Command wt -ErrorAction SilentlyContinue

if ($wt) {
    # Windows Terminal: 2탭 (운영 | 개발)
    # 각 탭: Service Runner (메인) + NSSM stdout + NSSM stderr (분할)

    $prodRunnerCmd = Get-TailCommand $prodRunnerLog "[PROD] Service Runner" "Cyan"
    $prodStdoutCmd = Get-TailCommand $prodNssmLog "[PROD] NSSM STDOUT" "Green"
    $prodStderrCmd = Get-TailCommand $prodNssmErrLog "[PROD] STDERR" "Red"

    $devRunnerCmd = Get-TailCommand $devRunnerLog "[DEV] Service Runner" "Cyan"
    $devStdoutCmd = Get-TailCommand $devNssmLog "[DEV] NSSM STDOUT" "Green"
    $devStderrCmd = Get-TailCommand $devNssmErrLog "[DEV] STDERR" "Red"

    # Production 탭 (3분할: Runner | STDOUT | STDERR)
    wt new-tab `
        --title "Production Logs" `
        powershell -NoExit -Command $prodRunnerCmd `; `
        split-pane -H `
        powershell -NoExit -Command $prodStdoutCmd `; `
        split-pane -V `
        powershell -NoExit -Command $prodStderrCmd `; `
    new-tab `
        --title "Development Logs" `
        powershell -NoExit -Command $devRunnerCmd `; `
        split-pane -H `
        powershell -NoExit -Command $devStdoutCmd `; `
        split-pane -V `
        powershell -NoExit -Command $devStderrCmd
} else {
    # Fallback: PowerShell 창 (Service Runner 로그만)
    $prodRunnerCmd = Get-TailCommand $prodRunnerLog "[PROD] Service Runner" "Cyan"
    $devRunnerCmd = Get-TailCommand $devRunnerLog "[DEV] Service Runner" "Green"

    Start-Process powershell -ArgumentList "-NoExit", "-Command", $prodRunnerCmd
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $devRunnerCmd
}
