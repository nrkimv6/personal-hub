# Monitor Page - Startup API Watchdog
# Windows 로그인 시 API Watchdog을 자동으로 시작합니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# api-watchdog.ps1을 호출하여 API 상태를 모니터링합니다.
# Note: 관리자 권한으로 실행하면 NSSM 재시작이 가능합니다.
#
# See: docs/2026-01-04-api-stability-improvements.md

param(
    [int]$Delay = 30  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiWatchdogScript = Join-Path $ScriptDir "api-watchdog.ps1"
$LogFile = Join-Path (Split-Path -Parent $ScriptDir) "logs\dev\startup_api_watchdog.log"

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

Write-Log "Startup API watchdog script started"

# API 서버가 응답할 때까지 대기 (최대 5분)
$apiUrl = "http://localhost:8001/api/v1/system/status"
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
    Write-Log "WARNING: API server not ready after $maxWait seconds, starting watchdog anyway"
}

Write-Log "Starting API watchdog (Development mode)..."

# api-watchdog.ps1 호출 (Development 모드)
try {
    # Run in a new hidden window to keep it running
    $process = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", $apiWatchdogScript, "-Dev" `
        -WorkingDirectory (Split-Path -Parent $ScriptDir) `
        -WindowStyle Hidden `
        -PassThru

    Write-Log "API watchdog started (PID: $($process.Id))"

    # Save PID for management
    $pidFile = Join-Path (Split-Path -Parent $ScriptDir) ".pids\api_watchdog_dev.pid"
    $pidDir = Split-Path -Parent $pidFile
    if (-not (Test-Path $pidDir)) {
        New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
    }
    $process.Id | Out-File $pidFile -Encoding ascii

    Write-Log "PID saved to $pidFile"
} catch {
    Write-Log "ERROR: Failed to start API watchdog: $_"
}
