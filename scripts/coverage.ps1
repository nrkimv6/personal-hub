<#
.SYNOPSIS
    테스트 커버리지 리포트 생성 스크립트

.DESCRIPTION
    pytest-cov를 사용하여 테스트 커버리지를 측정하고 리포트를 생성합니다.

.PARAMETER Html
    HTML 리포트를 생성합니다 (htmlcov/ 디렉토리)

.PARAMETER Open
    HTML 리포트 생성 후 브라우저에서 엽니다 (-Html 필요)

.PARAMETER Quick
    slow 마커가 붙은 테스트를 제외하고 빠르게 실행합니다

.PARAMETER MinCov
    최소 커버리지 퍼센트. 이 값 미만이면 테스트가 실패합니다 (기본: 0, 비활성화)

.PARAMETER Module
    특정 모듈만 커버리지 측정 (예: app.modules.naver_booking)

.PARAMETER Xml
    XML 리포트 생성 (CI 연동용, coverage.xml)

.EXAMPLE
    .\scripts\coverage.ps1
    # 기본 커버리지 측정 (터미널 출력)

.EXAMPLE
    .\scripts\coverage.ps1 -Html -Open
    # HTML 리포트 생성 후 브라우저에서 열기

.EXAMPLE
    .\scripts\coverage.ps1 -Quick -Html
    # slow 테스트 제외하고 빠르게 HTML 리포트 생성

.EXAMPLE
    .\scripts\coverage.ps1 -MinCov 70
    # 커버리지 70% 미만 시 실패
#>

param(
    [switch]$Html,
    [switch]$Open,
    [switch]$Quick,
    [switch]$Xml,
    [int]$MinCov = 0,
    [string]$Module = "app"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 가상환경 Python 경로
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    Write-Error "가상환경을 찾을 수 없습니다. .venv를 먼저 생성하세요."
    exit 1
}

# 기본 pytest 인자
$PytestArgs = @(
    "-m", "pytest",
    "tests/",
    "--cov=$Module",
    "--cov-report=term-missing"
)

# HTML 리포트
if ($Html) {
    $PytestArgs += "--cov-report=html"
}

# XML 리포트 (CI용)
if ($Xml) {
    $PytestArgs += "--cov-report=xml"
}

# slow 테스트 제외
if ($Quick) {
    $PytestArgs += "-m"
    $PytestArgs += "not slow"
}

# 최소 커버리지 설정
if ($MinCov -gt 0) {
    $PytestArgs += "--cov-fail-under=$MinCov"
}

Write-Host ""
Write-Host "=== 테스트 커버리지 측정 ===" -ForegroundColor Cyan
Write-Host "대상 모듈: $Module" -ForegroundColor Gray
if ($Quick) {
    Write-Host "모드: Quick (slow 테스트 제외)" -ForegroundColor Yellow
}
if ($MinCov -gt 0) {
    Write-Host "최소 커버리지: $MinCov%" -ForegroundColor Yellow
}
Write-Host ""

# pytest 실행
Push-Location $ProjectRoot
try {
    & $PythonPath @PytestArgs
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

# HTML 리포트 열기
if ($Html -and $Open -and $ExitCode -eq 0) {
    $HtmlPath = Join-Path $ProjectRoot "htmlcov\index.html"
    if (Test-Path $HtmlPath) {
        Write-Host ""
        Write-Host "HTML 리포트를 브라우저에서 엽니다..." -ForegroundColor Green
        Start-Process $HtmlPath
    }
}

# 결과 안내
Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "커버리지 측정 완료!" -ForegroundColor Green
    if ($Html) {
        Write-Host "HTML 리포트: htmlcov/index.html" -ForegroundColor Gray
    }
    if ($Xml) {
        Write-Host "XML 리포트: coverage.xml" -ForegroundColor Gray
    }
} else {
    Write-Host "테스트 실패 또는 커버리지 기준 미달" -ForegroundColor Red
}

exit $ExitCode
