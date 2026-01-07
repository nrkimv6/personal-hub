<#
.SYNOPSIS
    E2E 테스트 실행 스크립트

.DESCRIPTION
    개발 서버를 시작하고 Playwright E2E 테스트를 실행합니다.
    테스트 완료 후 서버를 자동 종료합니다.

.PARAMETER Test
    특정 테스트 파일 또는 패턴 (기본: 전체)

.PARAMETER Headed
    브라우저를 표시하며 실행 (디버깅용)

.PARAMETER NoServer
    서버를 시작하지 않음 (이미 실행 중인 경우)

.EXAMPLE
    .\scripts\run-e2e-tests.ps1
    .\scripts\run-e2e-tests.ps1 -Test "test_navigation"
    .\scripts\run-e2e-tests.ps1 -Headed
    .\scripts\run-e2e-tests.ps1 -NoServer
#>

param(
    [string]$Test = "",
    [switch]$Headed,
    [switch]$NoServer
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 색상 출력
function Write-Info { Write-Host $args -ForegroundColor Cyan }
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Warn { Write-Host $args -ForegroundColor Yellow }

Write-Info "=== E2E 테스트 실행 ==="

# 가상환경 활성화
$VenvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
}

# 테스트 경로
$TestPath = Join-Path $ProjectRoot "tests\e2e"
if ($Test) {
    $TestPath = Join-Path $TestPath "frontend\$Test*.py"
}

# Playwright 환경변수
if ($Headed) {
    $env:PWHEADLESS = "0"
} else {
    $env:PWHEADLESS = "1"
}

if ($NoServer) {
    # 서버 없이 바로 테스트 실행
    Write-Info "서버 시작 생략 (-NoServer)"
    Write-Info "테스트 실행: pytest $TestPath"

    Push-Location $ProjectRoot
    try {
        pytest $TestPath -v --tb=short
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} else {
    # with_server.py를 사용하여 서버와 함께 테스트 실행
    $WithServerScript = Join-Path $ProjectRoot "tests\e2e\scripts\with_server.py"

    Write-Info "서버 시작 및 테스트 실행..."
    Write-Info "  API: http://localhost:8001"
    Write-Info "  Frontend: http://localhost:6101"

    Push-Location $ProjectRoot
    try {
        python $WithServerScript `
            --server "python -m uvicorn app.main:app --host 0.0.0.0 --port 8001" `
            --port 8001 `
            --server "npm run dev --prefix frontend -- --port 6101" `
            --port 6101 `
            --timeout 60 `
            -- pytest $TestPath -v --tb=short

        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

if ($exitCode -eq 0) {
    Write-Success "`n=== 테스트 성공 ==="
} else {
    Write-Warn "`n=== 테스트 실패 (exit code: $exitCode) ==="
}

exit $exitCode
