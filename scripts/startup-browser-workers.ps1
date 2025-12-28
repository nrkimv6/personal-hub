# Monitor Page - Startup Browser Workers
# Windows 로그인 시 브라우저 기반 워커를 자동으로 시작합니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# browser-workers.ps1을 호출하여 워커를 시작합니다.
# Note: 브라우저 워커는 사용자 세션에서 실행되어야 합니다.

param(
    [int]$Delay = 20  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$browserWorkersScript = Join-Path $ScriptDir "browser-workers.ps1"
$LogFile = Join-Path (Split-Path -Parent $ScriptDir) "logs\dev\startup_browser_workers.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"

    # Ensure log directory exists
    $logDir = Split-Path -Parent $LogFile
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Add-Content -Path $LogFile -Value $logMessage -Encoding UTF8
}

Write-Log "Startup browser workers script started"

# API 서버가 응답할 때까지 대기 (최대 5분)
$apiUrl = "http://localhost:8001/health"
$maxWait = 300  # 5분
$waited = 0
$checkInterval = 5

Write-Log "Waiting for API server ($apiUrl) to be ready..."

while ($waited -lt $maxWait) {
    try {
        $response = Invoke-WebRequest -Uri $apiUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Log "API server is ready after $waited seconds"
            break
        }
    } catch {
        # API 아직 안 됨
    }

    Start-Sleep -Seconds $checkInterval
    $waited += $checkInterval

    if ($waited % 30 -eq 0) {
        Write-Log "Still waiting for API server... ($waited seconds elapsed)"
    }
}

if ($waited -ge $maxWait) {
    Write-Log "WARNING: API server not ready after $maxWait seconds, starting workers anyway"
}

Write-Log "Starting browser workers..."

# browser-workers.ps1 호출
try {
    & $browserWorkersScript -Action start
    Write-Log "Browser workers start command completed"
} catch {
    Write-Log "ERROR: Failed to start browser workers: $_"
}
