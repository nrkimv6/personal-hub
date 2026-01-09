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

# ============================================================
# STEP 0: Start Redis (Podman)
# ============================================================
Write-Log "Starting Redis via Podman..."

$redisStarted = $false
$ProjectRoot = Split-Path -Parent $ScriptDir

try {
    # Podman machine 상태 확인
    Write-Log "  Checking Podman machine status..."
    $machineList = & podman machine list --format json 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Log "  Podman machine not running, starting..."
        & podman machine start 2>&1 | ForEach-Object { Write-Log "    $_" }
        Start-Sleep -Seconds 15  # WSL2 VM 초기화 대기
    } else {
        # JSON 파싱하여 실행 중인지 확인
        try {
            $machines = $machineList | ConvertFrom-Json
            $running = $machines | Where-Object { $_.Running -eq $true }

            if (-not $running) {
                Write-Log "  Podman machine not running, starting..."
                & podman machine start 2>&1 | ForEach-Object { Write-Log "    $_" }
                Start-Sleep -Seconds 15
            } else {
                Write-Log "  Podman machine already running"
            }
        } catch {
            # JSON 파싱 실패 시 podman ps로 연결 확인
            & podman ps 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Log "  Podman machine not connected, starting..."
                & podman machine start 2>&1 | ForEach-Object { Write-Log "    $_" }
                Start-Sleep -Seconds 15
            } else {
                Write-Log "  Podman machine connected"
            }
        }
    }

    # Redis 컨테이너 시작
    Write-Log "  Starting Redis container..."
    Set-Location $ProjectRoot

    # podman-compose 경로 확인
    $PodmanCompose = Join-Path $ProjectRoot ".venv\Scripts\podman-compose.exe"
    if (-not (Test-Path $PodmanCompose)) {
        # 전역 podman-compose 사용
        $PodmanCompose = "podman-compose"
    }

    & $PodmanCompose up -d redis 2>&1 | ForEach-Object { Write-Log "    $_" }
    Start-Sleep -Seconds 3

    # Redis 연결 테스트
    Write-Log "  Testing Redis connection..."
    $pingResult = & podman exec monitor-redis redis-cli ping 2>&1
    if ($pingResult -eq "PONG") {
        Write-Log "  Redis started successfully (PONG received)"
        $redisStarted = $true
    } else {
        Write-Log "  WARNING: Redis ping failed: $pingResult"
    }
} catch {
    Write-Log "  ERROR: Redis start failed: $_"
    Write-Log "  Workers will use SQLite fallback mode"
}

if (-not $redisStarted) {
    Write-Log "  Redis not available, workers will use SQLite fallback mode"
}

# ============================================================
# STEP 1: Wait for API Server
# ============================================================
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
