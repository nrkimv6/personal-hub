# Monitor Page - Startup Log Viewer
# Windows 부팅 후 서비스 로그 창을 자동으로 엽니다.
# 시작 프로그램에 등록하여 사용합니다.

param(
    [int]$Delay = 15  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"

# 서비스가 시작될 때까지 대기
Start-Sleep -Seconds $Delay

# 서비스 로그 파일 경로
$stdoutLog = Join-Path $LogDir "service_MonitorPage.log"
$stderrLog = Join-Path $LogDir "service_MonitorPage_err.log"

# Windows Terminal 확인
$wt = Get-Command wt -ErrorAction SilentlyContinue

if ($wt) {
    # Windows Terminal: 2분할 (stdout | stderr)
    wt new-tab `
        --title "MonitorPage Service Logs" `
        powershell -NoExit -Command "Write-Host 'STDOUT Log' -ForegroundColor Cyan; Get-Content '$stdoutLog' -Wait -Tail 100 -Encoding UTF8" `; `
        split-pane -H `
        powershell -NoExit -Command "Write-Host 'STDERR Log' -ForegroundColor Red; Get-Content '$stderrLog' -Wait -Tail 100 -Encoding UTF8"
} else {
    # Fallback: 일반 PowerShell 창
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Service Log' -ForegroundColor Cyan; Get-Content '$stdoutLog' -Wait -Tail 100 -Encoding UTF8"
}
