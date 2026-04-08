<#
.SYNOPSIS
    Gemini 3.1 Pro oneshot 덤프트럭 실행 래퍼.

.DESCRIPTION
    dumptruck_builder.py로 컨텍스트를 조립한 뒤,
    quota 사용량을 확인하고 Gemini CLI로 단발(oneshot) 호출을 실행합니다.
    결과는 docs\dumptruck\YYYY-MM-DD_$Topic.md 에 저장됩니다.

.PARAMETER Template
    사용할 템플릿 이름 (architecture, refactor, conflict, logdump)

.PARAMETER Include
    포함할 파일 glob 패턴 목록 (여러 개 가능)

.PARAMETER Exclude
    제외할 파일 glob 패턴 목록 (여러 개 가능, 선택)

.PARAMETER Topic
    출력 파일명에 사용할 주제 문자열 (예: "llm-registry-arch")

.EXAMPLE
    .\scripts\dumptruck_run.ps1 `
        -Template architecture `
        -Include "app/shared/**","app/modules/llm/**" `
        -Topic "llm-arch"
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("architecture", "refactor", "conflict", "logdump")]
    [string]$Template,

    [Parameter(Mandatory = $false)]
    [string[]]$Include = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$Exclude = @(),

    [Parameter(Mandatory = $true)]
    [string]$Topic
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Python 실행 경로
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python 실행 파일을 찾을 수 없습니다: $PythonExe"
    exit 1
}

# Builder 스크립트 경로
$BuilderScript = Join-Path $ScriptDir "dumptruck_builder.py"
if (-not (Test-Path $BuilderScript)) {
    Write-Error "Builder 스크립트를 찾을 수 없습니다: $BuilderScript"
    exit 1
}

# 임시 입력 파일 경로
$TmpGuid = [guid]::NewGuid().ToString()
$TmpInput = Join-Path $env:TEMP "dumptruck_$TmpGuid.txt"

try {
    # ──────────────────────────────────────────────────────────────────────────
    # 1. 컨텍스트 빌더 호출
    # ──────────────────────────────────────────────────────────────────────────
    Write-Host "[DUMPTRUCK] 컨텍스트 빌더 실행 중..." -ForegroundColor Cyan

    $BuilderArgs = @(
        $BuilderScript,
        "--template", $Template,
        "--out", $TmpInput
    )
    if ($Include.Count -gt 0) {
        $BuilderArgs += "--include"
        $BuilderArgs += $Include
    }
    if ($Exclude.Count -gt 0) {
        $BuilderArgs += "--exclude"
        $BuilderArgs += $Exclude
    }

    & $PythonExe @BuilderArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[DUMPTRUCK] Builder 실패 (exit $LASTEXITCODE). --force 추가 또는 include 범위 축소가 필요합니다."
        exit $LASTEXITCODE
    }

    $InputSize = (Get-Item $TmpInput).Length
    Write-Host "[DUMPTRUCK] 입력 파일 생성 완료: $([math]::Round($InputSize / 1MB, 2)) MB" -ForegroundColor Green

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Quota 사전 확인
    # ──────────────────────────────────────────────────────────────────────────
    Write-Host "[DUMPTRUCK] Quota 상태 조회 중..." -ForegroundColor Cyan
    try {
        $QuotaResp = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/llm/quota" -Method Get -TimeoutSec 5
        $GeminiQuota = $QuotaResp.entries | Where-Object { $_.provider -eq "gemini" } | Select-Object -First 1

        if ($null -ne $GeminiQuota) {
            $Pct = [int]$GeminiQuota.weekly_used_pct
            Write-Host "[DUMPTRUCK] Gemini 주간 사용량: $Pct%" -ForegroundColor Yellow

            if ($Pct -ge 80) {
                $Answer = Read-Host "사용량 ${Pct}%, 계속하시겠습니까? (y/N)"
                if ($Answer -notmatch "^[yY]$") {
                    Write-Host "[DUMPTRUCK] 사용자가 취소했습니다." -ForegroundColor Red
                    exit 0
                }
            }
        } else {
            Write-Host "[DUMPTRUCK] Gemini quota 정보를 찾지 못했습니다. 계속 진행합니다." -ForegroundColor Yellow
        }
    } catch {
        Write-Warning "[DUMPTRUCK] Quota 조회 실패 (API 미기동?): $_. 확인 없이 계속합니다."
    }

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Gemini CLI 호출
    # ──────────────────────────────────────────────────────────────────────────
    Write-Host "[DUMPTRUCK] Gemini CLI 호출 중 (oneshot)..." -ForegroundColor Cyan

    # 출력 파일 경로
    $DateStr = Get-Date -Format "yyyy-MM-dd"
    $OutputDir = Join-Path $ProjectRoot "docs\dumptruck"
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    $OutputFile = Join-Path $OutputDir "${DateStr}_${Topic}.md"

    # stdin 파이프 방식으로 호출 (8191자 명령행 제한 우회)
    $GeminiOutput = Get-Content -Path $TmpInput -Raw | gemini --print
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[DUMPTRUCK] Gemini CLI 호출 실패 (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }

    $GeminiOutput | Out-File -FilePath $OutputFile -Encoding utf8
    Write-Host "[DUMPTRUCK] 결과 저장: $OutputFile" -ForegroundColor Green

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Quota delta 보고
    # ──────────────────────────────────────────────────────────────────────────
    Write-Host "[DUMPTRUCK] Quota delta 보고 중..." -ForegroundColor Cyan
    try {
        $ReportBody = @{
            provider        = "gemini"
            model           = "gemini-3.1-pro"
            delta_weekly_pct = 10
        } | ConvertTo-Json

        Invoke-RestMethod `
            -Uri "http://localhost:8001/api/v1/llm/quota/report" `
            -Method Post `
            -Body $ReportBody `
            -ContentType "application/json" `
            -TimeoutSec 5 | Out-Null

        Write-Host "[DUMPTRUCK] Quota +10% delta 보고 완료." -ForegroundColor Green
    } catch {
        Write-Warning "[DUMPTRUCK] Quota delta 보고 실패: $_. 수동으로 quota를 업데이트하세요."
    }

    Write-Host "[DUMPTRUCK] 완료! 결과 파일: $OutputFile" -ForegroundColor Green

} finally {
    # 임시 입력 파일 삭제 보장
    if (Test-Path $TmpInput) {
        Remove-Item -Path $TmpInput -Force
        Write-Verbose "[DUMPTRUCK] 임시 파일 삭제: $TmpInput"
    }
}
