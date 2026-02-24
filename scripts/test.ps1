<#
.SYNOPSIS
    pytest 테스트 실행 스크립트

.DESCRIPTION
    워커 실행 중 테스트 실행 시 경고를 표시하고,
    안전하게 테스트를 실행합니다.

.PARAMETER Force
    워커 실행 중에도 강제로 테스트 실행

.PARAMETER Slow
    느린 테스트 포함 실행 (기본: 제외)

.PARAMETER Integration
    Integration 테스트만 실행

.PARAMETER Args
    pytest에 전달할 추가 인자

.EXAMPLE
    .\scripts\test.ps1
    # 기본 테스트 실행 (느린 테스트 제외)

.EXAMPLE
    .\scripts\test.ps1 -Force
    # 워커 실행 중에도 강제 실행

.EXAMPLE
    .\scripts\test.ps1 -Slow
    # 느린 테스트 포함 실행

.EXAMPLE
    .\scripts\test.ps1 -Integration
    # Integration 테스트만 실행

.EXAMPLE
    .\scripts\test.ps1 tests\test_slot_check_api.py -v
    # 특정 테스트 파일 실행
#>

param(
    [switch]$Force,
    [switch]$Slow,
    [switch]$Integration,
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$Args
)

$workerPidFile = ".pids\worker.pid"

# 워커 실행 중 확인
if ((Test-Path $workerPidFile) -and -not $Force) {
    $pid = Get-Content $workerPidFile -ErrorAction SilentlyContinue
    $process = Get-Process -Id $pid -ErrorAction SilentlyContinue

    if ($process) {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Yellow
        Write-Host "  WARNING: Worker is running (PID: $pid)" -ForegroundColor Yellow
        Write-Host "  Some tests that access production DB will be skipped." -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Options:" -ForegroundColor Cyan
        Write-Host "  1. Stop worker first: .\scripts\stop.ps1"
        Write-Host "  2. Force run: .\scripts\test.ps1 -Force"
        Write-Host ""
        Write-Host "Continuing with tests (production DB tests will be skipped)..." -ForegroundColor Gray
        Write-Host ""
    }
}

# pytest 인자 구성
$pytestArgs = @()

if ($Integration) {
    $pytestArgs += "tests/integration/"
} elseif ($Args.Count -eq 0) {
    $pytestArgs += "tests/"
    if (-not $Slow) {
        $pytestArgs += "-m"
        $pytestArgs += "not slow"
    }
}

# 추가 인자 병합
$pytestArgs += $Args

# 테스트 실행
Write-Host "Running: pytest $($pytestArgs -join ' ')" -ForegroundColor Cyan
Write-Host ""

python -m pytest @pytestArgs
