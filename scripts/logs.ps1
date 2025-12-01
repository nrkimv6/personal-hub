# Monitor Page - 로그 뷰어 스크립트
# API 서버와 워커의 로그를 실시간으로 확인합니다.

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "api", "worker", "list")]
    [string]$Target = "all",

    [Parameter()]
    [int]$Lines = 50,

    [Parameter()]
    [switch]$Follow,

    [Parameter()]
    [switch]$Help
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"

# 도움말 출력
if ($Help) {
    Write-Host @"

Monitor Page 로그 뷰어
======================

사용법:
    .\logs.ps1 [target] [-Lines N] [-Follow] [-Help]

대상 (target):
    all      API와 워커 로그를 동시에 표시 (기본값)
    api      API 서버 로그만 표시
    worker   워커 로그만 표시
    list     사용 가능한 로그 파일 목록 표시

옵션:
    -Lines N    표시할 줄 수 (기본값: 50)
    -Follow     실시간으로 로그 추적 (tail -f)
    -Help       이 도움말 표시

예제:
    .\logs.ps1                  # 모든 로그의 최근 50줄 표시
    .\logs.ps1 api              # API 로그만 표시
    .\logs.ps1 worker -Lines 100  # 워커 로그 최근 100줄 표시
    .\logs.ps1 all -Follow      # 모든 로그 실시간 추적

"@
    exit 0
}

# 로그 디렉토리 확인
if (-not (Test-Path $LogDir)) {
    Write-Host "[!] 로그 디렉토리가 없습니다: $LogDir" -ForegroundColor Red
    exit 1
}

# 최신 로그 파일 찾기 함수
function Get-LatestLogFile {
    param([string]$Prefix)

    $pattern = Join-Path $LogDir "$Prefix*.log"
    $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($files) {
        return $files[0].FullName
    }
    return $null
}

# 로그 파일 목록 표시
if ($Target -eq "list") {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  사용 가능한 로그 파일" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # API 로그
    Write-Host "[API 서버 로그]" -ForegroundColor Yellow
    $apiLogs = Get-ChildItem (Join-Path $LogDir "api_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($apiLogs) {
        foreach ($log in $apiLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (없음)" -ForegroundColor Gray
    }

    Write-Host ""

    # 워커 로그
    Write-Host "[워커 로그]" -ForegroundColor Yellow
    $workerLogs = Get-ChildItem (Join-Path $LogDir "worker_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($workerLogs) {
        foreach ($log in $workerLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (없음)" -ForegroundColor Gray
    }

    Write-Host ""
    exit 0
}

# 로그 파일 가져오기
$apiLogFile = Get-LatestLogFile "api_"
$workerLogFile = Get-LatestLogFile "worker_"

# 로그 내용 표시 함수
function Show-LogContent {
    param(
        [string]$FilePath,
        [string]$Label,
        [ConsoleColor]$Color,
        [int]$TailLines
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[$Label] 로그 파일 없음" -ForegroundColor Gray
        return
    }

    Write-Host "`n========================================" -ForegroundColor $Color
    Write-Host "  $Label 로그" -ForegroundColor $Color
    Write-Host "  파일: $(Split-Path $FilePath -Leaf)" -ForegroundColor $Color
    Write-Host "========================================" -ForegroundColor $Color
    Write-Host ""

    # 최근 N줄 읽기
    $content = Get-Content $FilePath -Tail $TailLines -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($content) {
        foreach ($line in $content) {
            # 로그 레벨에 따라 색상 지정
            $lineColor = "White"
            if ($line -match "ERROR|CRITICAL") {
                $lineColor = "Red"
            } elseif ($line -match "WARNING") {
                $lineColor = "Yellow"
            } elseif ($line -match "INFO") {
                $lineColor = "Green"
            } elseif ($line -match "DEBUG") {
                $lineColor = "Gray"
            }
            Write-Host $line -ForegroundColor $lineColor
        }
    } else {
        Write-Host "(로그 내용 없음)" -ForegroundColor Gray
    }
}

# 실시간 로그 추적 함수 (단일 파일)
function Start-LogTail {
    param(
        [string]$FilePath,
        [string]$Prefix
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[!] 로그 파일이 없습니다: $Prefix" -ForegroundColor Red
        return
    }

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  실시간 로그 추적: $Prefix" -ForegroundColor Cyan
    Write-Host "  파일: $(Split-Path $FilePath -Leaf)" -ForegroundColor Cyan
    Write-Host "  종료: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # PowerShell의 Get-Content -Wait 사용
    Get-Content $FilePath -Wait -Tail 10 -Encoding UTF8 | ForEach-Object {
        $line = $_
        $lineColor = "White"
        if ($line -match "ERROR|CRITICAL") {
            $lineColor = "Red"
        } elseif ($line -match "WARNING") {
            $lineColor = "Yellow"
        } elseif ($line -match "INFO") {
            $lineColor = "Green"
        } elseif ($line -match "DEBUG") {
            $lineColor = "Gray"
        }
        Write-Host $line -ForegroundColor $lineColor
    }
}

# 실시간 로그 추적 (통합)
function Start-CombinedLogTail {
    param(
        [string]$ApiLog,
        [string]$WorkerLog
    )

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  실시간 통합 로그 추적" -ForegroundColor Cyan
    Write-Host "  종료: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # 두 파일의 변경을 모니터링하는 작업 생성
    $jobs = @()

    if ($ApiLog -and (Test-Path $ApiLog)) {
        $job = Start-Job -ScriptBlock {
            param($logPath)
            Get-Content $logPath -Wait -Tail 5 -Encoding UTF8 | ForEach-Object {
                "[API] $_"
            }
        } -ArgumentList $ApiLog
        $jobs += $job
    }

    if ($WorkerLog -and (Test-Path $WorkerLog)) {
        $job = Start-Job -ScriptBlock {
            param($logPath)
            Get-Content $logPath -Wait -Tail 5 -Encoding UTF8 | ForEach-Object {
                "[WORKER] $_"
            }
        } -ArgumentList $WorkerLog
        $jobs += $job
    }

    if ($jobs.Count -eq 0) {
        Write-Host "[!] 추적할 로그 파일이 없습니다." -ForegroundColor Red
        return
    }

    try {
        while ($true) {
            foreach ($job in $jobs) {
                $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
                if ($output) {
                    foreach ($line in $output) {
                        $lineColor = "White"
                        if ($line -match "ERROR|CRITICAL") {
                            $lineColor = "Red"
                        } elseif ($line -match "WARNING") {
                            $lineColor = "Yellow"
                        } elseif ($line -match "INFO") {
                            $lineColor = "Green"
                        } elseif ($line -match "DEBUG") {
                            $lineColor = "Gray"
                        }

                        # API vs Worker 구분 색상
                        if ($line -match "^\[API\]") {
                            Write-Host $line -ForegroundColor Cyan
                        } elseif ($line -match "^\[WORKER\]") {
                            Write-Host $line -ForegroundColor Magenta
                        } else {
                            Write-Host $line -ForegroundColor $lineColor
                        }
                    }
                }
            }
            Start-Sleep -Milliseconds 100
        }
    } finally {
        # 작업 정리
        $jobs | Stop-Job -ErrorAction SilentlyContinue
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    }
}

# 메인 로직
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page 로그 뷰어" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 실시간 추적 모드
if ($Follow) {
    switch ($Target) {
        "api" {
            Start-LogTail -FilePath $apiLogFile -Prefix "API"
        }
        "worker" {
            Start-LogTail -FilePath $workerLogFile -Prefix "Worker"
        }
        default {
            Start-CombinedLogTail -ApiLog $apiLogFile -WorkerLog $workerLogFile
        }
    }
} else {
    # 정적 로그 표시
    switch ($Target) {
        "api" {
            Show-LogContent -FilePath $apiLogFile -Label "API 서버" -Color Cyan -TailLines $Lines
        }
        "worker" {
            Show-LogContent -FilePath $workerLogFile -Label "워커" -Color Magenta -TailLines $Lines
        }
        default {
            Show-LogContent -FilePath $apiLogFile -Label "API 서버" -Color Cyan -TailLines $Lines
            Show-LogContent -FilePath $workerLogFile -Label "워커" -Color Magenta -TailLines $Lines
        }
    }
}

Write-Host ""
