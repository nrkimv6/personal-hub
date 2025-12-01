# Monitor Page - 백그라운드 실행 스크립트
# FastAPI 서버와 모니터링 워커를 백그라운드에서 실행합니다.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# 로그 디렉토리 생성
$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# PID 파일 경로
$PidDir = Join-Path $ProjectRoot ".pids"
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"

# 이미 실행 중인 프로세스 확인
function Test-ProcessRunning {
    param([string]$PidFile)

    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($pid) {
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                return $true
            }
        }
    }
    return $false
}

# API 서버 확인
if (Test-ProcessRunning $ApiPidFile) {
    $apiPid = Get-Content $ApiPidFile
    Write-Host "[!] API 서버가 이미 실행 중입니다 (PID: $apiPid)" -ForegroundColor Yellow
    $runApi = $false
} else {
    $runApi = $true
}

# 워커 확인
if (Test-ProcessRunning $WorkerPidFile) {
    $workerPid = Get-Content $WorkerPidFile
    Write-Host "[!] 워커가 이미 실행 중입니다 (PID: $workerPid)" -ForegroundColor Yellow
    $runWorker = $false
} else {
    $runWorker = $true
}

# 둘 다 실행 중이면 종료
if (-not $runApi -and -not $runWorker) {
    Write-Host "`n모든 프로세스가 이미 실행 중입니다." -ForegroundColor Green
    Write-Host "로그 보기: .\scripts\logs.ps1"
    Write-Host "프로세스 종료: .\scripts\stop.ps1"
    exit 0
}

# 작업 디렉토리 변경
Set-Location $ProjectRoot

# 가상환경 활성화 (있는 경우)
$VenvPath = Join-Path $ProjectRoot "venv\Scripts\Activate.ps1"
$VenvPath2 = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"

if (Test-Path $VenvPath) {
    Write-Host "[*] 가상환경 활성화 중..." -ForegroundColor Cyan
    & $VenvPath
} elseif (Test-Path $VenvPath2) {
    Write-Host "[*] 가상환경 활성화 중..." -ForegroundColor Cyan
    & $VenvPath2
}

# 타임스탬프 생성
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Monitor Page 백그라운드 실행" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# API 서버 시작 (워커 자동 시작 비활성화)
if ($runApi) {
    Write-Host "[*] API 서버 시작 중..." -ForegroundColor Cyan

    # 환경 변수 설정 (워커 자동 시작 비활성화)
    $env:WORKER_AUTO_START = "false"

    $apiLogFile = Join-Path $LogDir "api_$Timestamp.log"

    # 백그라운드에서 API 서버 실행
    $apiProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $apiLogFile `
        -RedirectStandardError $apiLogFile `
        -PassThru

    # PID 저장
    $apiProcess.Id | Out-File $ApiPidFile -Encoding ascii

    Write-Host "[+] API 서버 시작됨 (PID: $($apiProcess.Id))" -ForegroundColor Green
    Write-Host "    로그: $apiLogFile"
}

# 잠시 대기 (API 서버 초기화 시간)
Start-Sleep -Seconds 2

# 워커 시작
if ($runWorker) {
    Write-Host "`n[*] 워커 시작 중..." -ForegroundColor Cyan

    $workerLogFile = Join-Path $LogDir "worker_$Timestamp.log"

    # 백그라운드에서 워커 실행
    $workerProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "app.worker.monitor_worker" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $workerLogFile `
        -RedirectStandardError $workerLogFile `
        -PassThru

    # PID 저장
    $workerProcess.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Host "[+] 워커 시작됨 (PID: $($workerProcess.Id))" -ForegroundColor Green
    Write-Host "    로그: $workerLogFile"
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  모든 프로세스가 시작되었습니다" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "API 서버: http://localhost:8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "유용한 명령어:" -ForegroundColor Yellow
Write-Host "  로그 보기:       .\scripts\logs.ps1"
Write-Host "  프로세스 종료:   .\scripts\stop.ps1"
Write-Host ""
