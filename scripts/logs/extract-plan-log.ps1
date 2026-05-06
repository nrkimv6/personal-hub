<#
.SYNOPSIS
    plan-runner 로그 파일에서 특정 runner_id(plan) 구간을 추출한다.

.DESCRIPTION
    _dr_plan_runner.py가 출력하는 "[plan:<runner_id> start]" / "[plan:<runner_id> end]" 마커
    사이의 줄을 잘라내어 logs/plan-runs/<runner_id>.log 에 저장한다.

.PARAMETER Plan
    추출 대상 runner_id (예: abc123def456)

.PARAMETER LogFile
    파싱할 원본 로그 파일 경로. 생략 시 logs/dev-runner/ 에서 가장 최근 파일을 자동 선택.

.PARAMETER OutDir
    출력 디렉토리. 기본값: <ProjectRoot>/logs/plan-runs/

.EXAMPLE
    .\scripts\logs\extract-plan-log.ps1 -Plan abc123def456
    .\scripts\logs\extract-plan-log.ps1 -Plan abc123def456 -LogFile "D:\...\logs\dev-runner\2026-04-26.log"
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Plan,

    [string]$LogFile = "",

    [string]$OutDir = ""
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if (-not $OutDir) {
    $OutDir = Join-Path $ProjectRoot "logs\plan-runs"
}

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

# 로그 파일 자동 탐색
if (-not $LogFile) {
    $LogDir = Join-Path $ProjectRoot "logs\dev-runner"
    if (-not (Test-Path $LogDir)) {
        Write-Error "로그 디렉토리를 찾을 수 없습니다: $LogDir"
        exit 1
    }
    $Latest = Get-ChildItem -Path $LogDir -Filter "*.log" -File |
              Sort-Object LastWriteTime -Descending |
              Select-Object -First 1
    if (-not $Latest) {
        Write-Error "dev-runner 로그 파일이 없습니다: $LogDir"
        exit 1
    }
    $LogFile = $Latest.FullName
    Write-Host "자동 선택된 로그 파일: $LogFile"
}

if (-not (Test-Path $LogFile)) {
    Write-Error "로그 파일을 찾을 수 없습니다: $LogFile"
    exit 1
}

$StartMarker = "[plan:$Plan start]"
$EndMarker   = "[plan:$Plan end]"
$OutFile     = Join-Path $OutDir "$Plan.log"

$lines      = [System.IO.File]::ReadAllLines($LogFile, [System.Text.Encoding]::UTF8)
$capturing  = $false
$collected  = [System.Collections.Generic.List[string]]::new()
$foundStart = $false
$foundEnd   = $false

foreach ($line in $lines) {
    if (-not $capturing) {
        if ($line.TrimEnd() -eq $StartMarker) {
            $capturing  = $true
            $foundStart = $true
            $collected.Add($line)
        }
    } else {
        $collected.Add($line)
        if ($line.TrimEnd() -eq $EndMarker) {
            $foundEnd = $true
            break
        }
    }
}

if (-not $foundStart) {
    Write-Warning "시작 마커를 찾을 수 없습니다: $StartMarker"
    Write-Warning "로그 파일: $LogFile"
    exit 1
}

if (-not $foundEnd) {
    Write-Warning "종료 마커를 찾을 수 없습니다: $EndMarker — 실행이 아직 진행 중이거나 비정상 종료됨"
}

[System.IO.File]::WriteAllLines($OutFile, $collected, [System.Text.Encoding]::UTF8)
Write-Host "추출 완료: $OutFile ($($collected.Count)줄)"
