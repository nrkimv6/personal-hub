# Auto-Update Script
# Git pull 후 변경된 코드에 따라 API/워커를 자동 재시작합니다.
#
# Usage:
#   .\scripts\auto-update.ps1                          # main 브랜치에서 pull
#   .\scripts\auto-update.ps1 -Branch feature/xxx      # 특정 브랜치에서 pull
#   .\scripts\auto-update.ps1 -Force                   # 변경 없어도 강제 재시작
#   .\scripts\auto-update.ps1 -ApiOnly                 # API만 재시작
#   .\scripts\auto-update.ps1 -WorkerOnly              # 워커만 재시작
#
# 동작 방식:
#   1. git pull --ff-only (fast-forward만 허용, 충돌 방지)
#   2. 변경된 파일 분석 → API/워커 코드 변경 여부 판단
#   3. API 변경 시: self-restart API 호출 (graceful shutdown → NSSM 자동 재시작)
#   4. 워커 변경 시: browser-workers.ps1 -Action restart (관리자 권한 불필요)
#
# 관리자 권한: 불필요 (모든 작업이 사용자 권한으로 수행)
#
# Task Scheduler 등록 예시 (5분마다 자동 업데이트):
#   schtasks /create /tn "MonitorPage-AutoUpdate" /tr "pwsh -File D:\work\project\tools\monitor-page\scripts\auto-update.ps1" /sc minute /mo 5

param(
    [string]$Branch = "main",
    [switch]$Force,
    [switch]$ApiOnly,
    [switch]$WorkerOnly,
    [int]$ApiPort = 8001,
    [float]$ShutdownDelay = 2.0
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# 로그 설정
$LogDir = Join-Path $ProjectRoot "logs\dev"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir "auto_update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$Level] $Message"
    Write-Host $logEntry
    Add-Content -Path $LogFile -Value $logEntry -Encoding UTF8
}

# ============================================================
# 1. Git Pull
# ============================================================
Write-Log "=== Auto-Update 시작 (Branch: $Branch) ==="

Set-Location $ProjectRoot

# 현재 커밋 해시 저장
$beforeHash = git rev-parse HEAD 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "git rev-parse 실패: $beforeHash" "ERROR"
    exit 1
}

# Git pull (fast-forward only)
$pullResult = git pull --ff-only origin $Branch 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "git pull 실패: $pullResult" "ERROR"
    Write-Log "충돌이 있을 수 있습니다. 수동으로 해결해주세요." "ERROR"
    exit 1
}

$afterHash = git rev-parse HEAD 2>&1

# 변경 확인
$hasChanges = $beforeHash -ne $afterHash

if (-not $hasChanges -and -not $Force) {
    Write-Log "변경 없음 (Already up to date)"
    exit 0
}

if ($hasChanges) {
    Write-Log "새 커밋 감지: $beforeHash -> $afterHash"
} else {
    Write-Log "변경 없음이지만 -Force 옵션으로 재시작 진행"
}

# ============================================================
# 2. 변경 파일 분석
# ============================================================
$restartApi = $false
$restartWorkers = $false

if ($hasChanges) {
    $changedFiles = git diff --name-only "$beforeHash" "$afterHash" 2>&1
    Write-Log "변경된 파일 수: $(($changedFiles | Measure-Object).Count)"

    foreach ($file in $changedFiles) {
        Write-Log "  변경: $file"

        # API 재시작이 필요한 경로 패턴
        if ($file -match "^app/(routes|modules|services|core|models|shared|database)" -or
            $file -match "^app/(main|config)\.py" -or
            $file -match "^app/migrations/") {
            $restartApi = $true
        }

        # 워커 재시작이 필요한 경로 패턴
        if ($file -match "^app/worker/" -or
            $file -match "^app/modules/.*/worker") {
            $restartWorkers = $true
        }

        # 프론트엔드 변경은 재시작 불필요 (SvelteKit dev server가 핫 리로드)
        # scripts/ 변경도 실행 중인 프로세스에 영향 없음
    }
}

# -Force 옵션이면 둘 다 재시작
if ($Force) {
    if (-not $ApiOnly -and -not $WorkerOnly) {
        $restartApi = $true
        $restartWorkers = $true
    }
}

# -ApiOnly / -WorkerOnly 옵션 처리
if ($ApiOnly) {
    $restartApi = $true
    $restartWorkers = $false
}
if ($WorkerOnly) {
    $restartApi = $false
    $restartWorkers = $true
}

if (-not $restartApi -and -not $restartWorkers) {
    Write-Log "API/워커 재시작 불필요 (프론트엔드/스크립트/문서만 변경)"
    exit 0
}

Write-Log "재시작 대상 - API: $restartApi, Workers: $restartWorkers"

# ============================================================
# 3. API Self-Restart (graceful)
# ============================================================
if ($restartApi) {
    Write-Log "API self-restart 호출 중 (port: $ApiPort, delay: ${ShutdownDelay}s)..."

    try {
        $uri = "http://localhost:$ApiPort/api/v1/system/self-restart?delay=$ShutdownDelay"
        $response = Invoke-RestMethod -Uri $uri -Method POST -TimeoutSec 10
        Write-Log "API self-restart 응답: $($response.message)"
        Write-Log "API가 ${ShutdownDelay}초 후 종료됩니다. NSSM이 ~10초 후 자동 재시작합니다."

        # API 재시작 완료 대기 (shutdown delay + NSSM throttle + startup)
        $waitSeconds = [int]$ShutdownDelay + 15
        Write-Log "API 재시작 대기 중 (${waitSeconds}초)..."
        Start-Sleep -Seconds $waitSeconds

        # API 상태 확인
        $maxRetries = 6
        $retryInterval = 5
        $apiReady = $false

        for ($i = 1; $i -le $maxRetries; $i++) {
            try {
                $status = Invoke-RestMethod -Uri "http://localhost:$ApiPort/api/v1/system/status" -Method GET -TimeoutSec 5
                Write-Log "API 재시작 완료 (PID: $($status.worker_pid), 시도: $i/$maxRetries)"
                $apiReady = $true
                break
            } catch {
                Write-Log "API 아직 준비 안 됨 (시도: $i/$maxRetries, ${retryInterval}초 후 재시도)" "WARN"
                Start-Sleep -Seconds $retryInterval
            }
        }

        if (-not $apiReady) {
            Write-Log "API 재시작 확인 실패 (${maxRetries}회 시도). 수동 확인 필요." "ERROR"
        }

    } catch {
        Write-Log "API self-restart 호출 실패: $($_.Exception.Message)" "ERROR"
        Write-Log "API가 이미 중지된 상태일 수 있습니다. NSSM이 자동으로 시작합니다." "WARN"
    }
}

# ============================================================
# 4. 워커 재시작
# ============================================================
if ($restartWorkers) {
    Write-Log "워커 재시작 시작..."

    try {
        $workerScript = Join-Path $ScriptDir "browser-workers.ps1"
        & $workerScript -Action restart
        Write-Log "워커 재시작 완료"
    } catch {
        Write-Log "워커 재시작 실패: $($_.Exception.Message)" "ERROR"
    }
}

# ============================================================
# 5. 완료
# ============================================================
Write-Log "=== Auto-Update 완료 ==="

if ($hasChanges) {
    # 변경 요약 출력
    $commitLog = git log --oneline "$beforeHash..$afterHash" 2>&1
    Write-Log "적용된 커밋:"
    foreach ($line in $commitLog) {
        Write-Log "  $line"
    }
}
