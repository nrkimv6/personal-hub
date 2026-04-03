<#
.SYNOPSIS
    dev_runner pytest를 파일 배치 단위로 분할 실행

.DESCRIPTION
    한 번에 `tests/dev_runner` 전체를 실행하면 메모리 사용량이 급증할 수 있어
    collect 결과를 파일 단위로 나눈 뒤 새 pytest 프로세스로 순차 실행한다.

.PARAMETER ChunkSize
    배치당 테스트 파일 수 (기본 12)

.PARAMETER IncludeHeavy
    e2e/integration/slow/full_e2e/http 마커 테스트 포함 실행

.PARAMETER ContinueOnFail
    실패 배치가 있어도 다음 배치 계속 실행

.PARAMETER Args
    각 pytest 실행에 추가 전달할 인자

.EXAMPLE
    .\scripts\test-dev-runner-batch.ps1

.EXAMPLE
    .\scripts\test-dev-runner-batch.ps1 -ChunkSize 8 -Args @("-v")

.EXAMPLE
    .\scripts\test-dev-runner-batch.ps1 -IncludeHeavy -ChunkSize 4
#>

param(
    [int]$ChunkSize = 12,
    [int]$StartBatch = 1,
    [int]$EndBatch = 0,
    [switch]$IncludeHeavy,
    [switch]$ContinueOnFail,
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$baseTarget = "tests/dev_runner"
$markerExpr = "not e2e and not integration and not slow and not full_e2e and not http"

if ($ChunkSize -lt 1) {
    throw "ChunkSize must be >= 1"
}
if ($StartBatch -lt 1) {
    throw "StartBatch must be >= 1"
}
if ($EndBatch -lt 0) {
    throw "EndBatch must be >= 0"
}

# 1) 대상 파일 수집
$collectArgs = @($baseTarget, "--collect-only", "-q")
if (-not $IncludeHeavy) {
    $collectArgs += @("-m", $markerExpr)
}

Write-Host "[collect] python -m pytest $($collectArgs -join ' ')" -ForegroundColor Cyan
$tmpCollect = [System.IO.Path]::GetTempFileName()
try {
    & python -m pytest @collectArgs > $tmpCollect 2>&1
    $collectExit = $LASTEXITCODE
    $collectOut = Get-Content -Path $tmpCollect -ErrorAction SilentlyContinue
} finally {
    Remove-Item -LiteralPath $tmpCollect -ErrorAction SilentlyContinue
}
if ($collectExit -ne 0) {
    $collectOut | Write-Host
    exit $collectExit
}

$nodeLines = $collectOut | Where-Object { $_ -match "(tests[/\\].+?\.py)::" }
$files = $nodeLines |
    ForEach-Object { [regex]::Match($_, "(tests[/\\].+?\.py)::").Groups[1].Value } |
    Where-Object { $_ -ne "" } |
    Sort-Object -Unique

if (-not $files -or $files.Count -eq 0) {
    Write-Host "[done] no files collected" -ForegroundColor Yellow
    exit 0
}

$totalBatches = [int][Math]::Ceiling($files.Count / [double]$ChunkSize)
$failed = 0

# 2) 배치 실행
for ($i = 0; $i -lt $files.Count; $i += $ChunkSize) {
    $batchNo = [int]($i / $ChunkSize) + 1
    if ($batchNo -lt $StartBatch) {
        continue
    }
    if ($EndBatch -gt 0 -and $batchNo -gt $EndBatch) {
        break
    }

    $end = [Math]::Min($i + $ChunkSize - 1, $files.Count - 1)
    $chunk = $files[$i..$end]

    $runArgs = @()
    $runArgs += $chunk
    $runArgs += @("--maxfail=1", "-q")
    if (-not $IncludeHeavy) {
        $runArgs += @("-m", $markerExpr)
    }
    $runArgs += $Args

    Write-Host ""
    Write-Host ("[batch {0}/{1}] files={2}" -f $batchNo, $totalBatches, $chunk.Count) -ForegroundColor Cyan
    & python -m pytest @runArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        $failed += 1
        Write-Host ("[batch {0}] failed (exit={1})" -f $batchNo, $exitCode) -ForegroundColor Red
        if (-not $ContinueOnFail) {
            exit $exitCode
        }
    } else {
        Write-Host ("[batch {0}] passed" -f $batchNo) -ForegroundColor Green
    }
}

if ($failed -gt 0) {
    Write-Host ("[done] completed with failures: {0}" -f $failed) -ForegroundColor Red
    exit 1
}

Write-Host "[done] all batches passed" -ForegroundColor Green
exit 0
