# Monitor Page - Startup Log Viewer
# Windows 부팅 후 서비스 로그 창을 자동으로 엽니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# Windows Terminal: 2탭 (운영 탭, 개발 탭)
# PowerShell: 2창 (운영 창, 개발 창)

param(
    [int]$Delay = 15  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"
$LogDirDev = Join-Path $ProjectRoot "logs\dev"

# 서비스가 시작될 때까지 대기
Start-Sleep -Seconds $Delay

# 서비스 로그 파일 경로
$prodLog = Join-Path $LogDir "service_MonitorPage.log"
$prodErrLog = Join-Path $LogDir "service_MonitorPage_err.log"
$devLog = Join-Path $LogDirDev "service_MonitorPage-Dev.log"
$devErrLog = Join-Path $LogDirDev "service_MonitorPage-Dev_err.log"

# Windows Terminal 확인
$wt = Get-Command wt -ErrorAction SilentlyContinue

if ($wt) {
    # Windows Terminal: 2탭 (운영 | 개발), 각 탭 2분할 (stdout | stderr)
    wt new-tab `
        --title "Production Logs" `
        powershell -NoExit -Command "Write-Host '[PROD] STDOUT' -ForegroundColor Cyan; Get-Content '$prodLog' -Wait -Tail 100 -Encoding UTF8" `; `
        split-pane -H `
        powershell -NoExit -Command "Write-Host '[PROD] STDERR' -ForegroundColor Red; Get-Content '$prodErrLog' -Wait -Tail 100 -Encoding UTF8" `; `
    new-tab `
        --title "Development Logs" `
        powershell -NoExit -Command "Write-Host '[DEV] STDOUT' -ForegroundColor Green; Get-Content '$devLog' -Wait -Tail 100 -Encoding UTF8" `; `
        split-pane -H `
        powershell -NoExit -Command "Write-Host '[DEV] STDERR' -ForegroundColor Red; Get-Content '$devErrLog' -Wait -Tail 100 -Encoding UTF8"
} else {
    # Fallback: 2개의 PowerShell 창
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host '[PROD] Service Log' -ForegroundColor Cyan; Get-Content '$prodLog' -Wait -Tail 100 -Encoding UTF8"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host '[DEV] Service Log' -ForegroundColor Green; Get-Content '$devLog' -Wait -Tail 100 -Encoding UTF8"
}
