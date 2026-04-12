# scripts/split-cloudflared-log.ps1
# cloudflared_err.log를 날짜별 파일로 분리하는 1회성 스크립트
# 사용법: .\scripts\split-cloudflared-log.ps1 [-DryRun]
#
# 분리 방식:
#   - 로그 형식: 2025-12-26T13:52:28Z INF/ERR ...
#   - 날짜 없는 줄(스택트레이스 등)은 직전 날짜에 포함
#   - 오늘(실행일) 날짜 로그만 원본에 남기고 Set-Content로 truncate
#   - NSSM이 파일 핸들 유지 중이므로 삭제 불가 → Set-Content로 내용 교체

param(
    [switch]$DryRun  # 테스트 모드 (실제 파일 쓰기 안함)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$LogDir = Join-Path $ProjectRoot "logs"
$InputFile = Join-Path $LogDir "cloudflared_err.log"

if (-not (Test-Path $InputFile)) {
    Write-Host "ERROR: 입력 파일이 없습니다: $InputFile"
    exit 1
}

$Today = (Get-Date).ToString("yyyy-MM-dd")
Write-Host "입력 파일: $InputFile"
Write-Host "오늘 날짜: $Today (이 날짜의 로그는 원본에 유지)"
Write-Host ""

# 날짜 → 줄 목록 맵
$dateMap = @{}  # key: "yyyy-MM-dd", value: [string[]]
$currentDate = $null

$lines = Get-Content $InputFile -Encoding UTF8 -ErrorAction Stop

Write-Host "총 $($lines.Count) 줄 읽음..."

foreach ($line in $lines) {
    if ($line -match '^\d{4}-\d{2}-\d{2}') {
        $currentDate = $line.Substring(0, 10)  # "yyyy-MM-dd"
    }
    # 날짜 없는 줄은 currentDate가 $null이면 스킵 (파일 상단 헤더 등)
    if ($null -eq $currentDate) { continue }

    if (-not $dateMap.ContainsKey($currentDate)) {
        $dateMap[$currentDate] = [System.Collections.Generic.List[string]]::new()
    }
    $dateMap[$currentDate].Add($line)
}

$sortedDates = $dateMap.Keys | Sort-Object
Write-Host "날짜별 분포:"
foreach ($d in $sortedDates) {
    $marker = if ($d -eq $Today) { " ← 오늘 (원본 유지)" } else { "" }
    Write-Host "  $d : $($dateMap[$d].Count) 줄$marker"
}
Write-Host ""

# 오늘 제외한 날짜별 파일 생성
$writtenFiles = 0
foreach ($d in $sortedDates) {
    if ($d -eq $Today) { continue }  # 오늘 날짜는 원본에 유지

    $dateStr = $d -replace "-", ""  # "20251226"
    $outFile = Join-Path $LogDir "cloudflared_err_$dateStr.log"

    if ($DryRun) {
        Write-Host "[DRY-RUN] 생성 예정: $outFile ($($dateMap[$d].Count) 줄)"
    } else {
        $dateMap[$d] | Set-Content -Path $outFile -Encoding UTF8 -Force
        Write-Host "생성: $outFile ($($dateMap[$d].Count) 줄)"
        $writtenFiles++
    }
}

# 원본 파일을 오늘 날짜 로그만 남기고 truncate (Set-Content 사용, 삭제 불가)
if ($dateMap.ContainsKey($Today)) {
    $todayLines = $dateMap[$Today]
    if ($DryRun) {
        Write-Host ""
        Write-Host "[DRY-RUN] 원본 truncate 예정: $InputFile ($($todayLines.Count) 줄만 유지)"
    } else {
        $todayLines | Set-Content -Path $InputFile -Encoding UTF8 -Force
        Write-Host ""
        Write-Host "원본 truncate 완료: $InputFile ($($todayLines.Count) 줄만 유지)"
    }
} else {
    # 오늘 날짜 로그가 없으면 원본 비우기
    if ($DryRun) {
        Write-Host ""
        Write-Host "[DRY-RUN] 원본 비우기 예정 (오늘 날짜 로그 없음): $InputFile"
    } else {
        Set-Content -Path $InputFile -Value "" -Encoding UTF8 -Force
        Write-Host ""
        Write-Host "원본 비움 (오늘 날짜 로그 없음): $InputFile"
    }
}

if (-not $DryRun) {
    Write-Host ""
    Write-Host "완료: $writtenFiles 개 날짜별 파일 생성"
    $inputSizeMB = (Get-Item $InputFile).Length / 1MB
    Write-Host "원본 크기: $([math]::Round($inputSizeMB, 3)) MB"
}
