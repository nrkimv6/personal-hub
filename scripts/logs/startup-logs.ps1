# Monitor Page - Startup Log Viewer
# Windows 부팅 후 서비스 로그 창을 자동으로 엽니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# Public 탭은 public-safe allowlist만 표시하고, Admin/Watchdog 탭은 운영 진단용 내부 로그를 유지합니다.

param(
    [int]$Delay = 15  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logsScript = Join-Path $ScriptDir "logs.ps1"

# 서비스가 시작될 때까지 대기
Start-Sleep -Seconds $Delay

# 탭별 logs.ps1 -Follow 명령어 생성
$publicSafeLogsCmd = @"
Write-Host '[PUBLIC] Monitor Page - Public Safe Log Viewer' -ForegroundColor Cyan
Write-Host 'Waiting for services to initialize...' -ForegroundColor Yellow
Start-Sleep -Seconds 3
& '$logsScript' -Follow -PublicSafe
"@

$adminLogsCmd = @"
Write-Host '[ADMIN] Monitor Page - Unified Log Viewer' -ForegroundColor Green
Write-Host 'Waiting for services to initialize...' -ForegroundColor Yellow
Start-Sleep -Seconds 3
& '$logsScript' -Follow -Admin
"@

$watchdogLogsCmd = @"
Write-Host '[WATCHDOG] Monitor Page - Watchdog Log Viewer' -ForegroundColor DarkYellow
Write-Host 'Waiting for services to initialize...' -ForegroundColor Yellow
Start-Sleep -Seconds 3
& '$logsScript' -Follow -Admin watchdog
"@

# Windows Terminal 확인
$wt = Get-Command wt -ErrorAction SilentlyContinue

if ($wt) {
    # Windows Terminal: 3탭 (운영 | 관리 | 워치독)
    wt new-tab `
        --title "Public Safe Logs" `
        powershell -NoExit -Command $publicSafeLogsCmd `; `
    new-tab `
        --title "Admin Logs" `
        powershell -NoExit -Command $adminLogsCmd `; `
    new-tab `
        --title "Watchdog Logs" `
        powershell -NoExit -Command $watchdogLogsCmd
} else {
    # Fallback: PowerShell 창 3개
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $publicSafeLogsCmd
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $adminLogsCmd
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $watchdogLogsCmd
}
