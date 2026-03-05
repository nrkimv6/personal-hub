# Monitor Page - Log Viewer Script
# View logs for API server, worker, and frontend in real-time

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "api", "worker", "frontend", "list", "watchdog")]
    [string]$Target = "all",

    [Parameter()]
    [int]$Lines = 50,

    [Parameter()]
    [switch]$Follow,

    [Parameter()]
    [switch]$FromStart,  # Show logs from beginning of file (not just tail)

    [Parameter()]
    [switch]$Admin,  # Use admin log directory (logs/admin/)

    [Parameter()]
    [switch]$Help
)

# Set console output encoding to UTF-8 for Korean support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Log directory based on mode
if ($Admin) {
    $LogDir = Join-Path $ProjectRoot "logs\admin"
    # Create admin log directory if it doesn't exist
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
}

# Show help
if ($Help) {
    Write-Host @"

Monitor Page Log Viewer
=======================

Usage:
    .\logs.ps1 [target] [-Lines N] [-Follow] [-Help]

Targets:
    all      Show API, Worker, and Frontend logs together (default)
    api      Show API server logs only
    worker   Show Worker logs only
    frontend Show Frontend logs only
    list     List available log files

Options:
    -Lines N    Number of lines to show (default: 50)
    -Follow     Follow logs in real-time (like tail -f)
    -Help       Show this help message

Examples:
    .\logs.ps1                  # Show last 50 lines of all logs
    .\logs.ps1 api              # Show API logs only
    .\logs.ps1 worker -Lines 100  # Show last 100 lines of worker logs
    .\logs.ps1 all -Follow      # Follow all logs in real-time

"@
    exit 0
}

# Check log directory
if (-not (Test-Path $LogDir)) {
    Write-Host "[!] Log directory not found: $LogDir" -ForegroundColor Red
    exit 1
}

# Get latest log file function (by LastWriteTime, not filename)
function Get-LatestLogFile {
    param([string]$Prefix)

    $pattern = Join-Path $LogDir "$Prefix*.log"
    $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($files) {
        return $files[0].FullName
    }
    return $null
}

# Plan-runner 로그 디렉토리 (list 블록에서도 사용하므로 여기서 먼저 정의)
$planRunnerLogDir = "D:\work\project\service\wtools\common\logs"

# List log files
if ($Target -eq "list") {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Available Log Files" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Helper to find logs with multiple patterns
    # Dev 모드일 때 base logs/ 디렉토리도 탐색 (API 앱의 LOG_DIR가 logs/ 고정)
    function Get-LogsMultiPattern {
        param([string[]]$Patterns)
        $searchDirs = @($LogDir)
        if ($Admin) {
            $baseLogDir = Join-Path $ProjectRoot "logs"
            if ($baseLogDir -ne $LogDir) { $searchDirs += $baseLogDir }
        }
        $allLogs = @()
        foreach ($dir in $searchDirs) {
            foreach ($pattern in $Patterns) {
                $found = Get-ChildItem (Join-Path $dir $pattern) -ErrorAction SilentlyContinue
                if ($found) { $allLogs += $found }
            }
        }
        return $allLogs | Sort-Object LastWriteTime -Descending
    }

    # API logs
    Write-Host "[API Server Logs]" -ForegroundColor Yellow
    $apiLogs = Get-LogsMultiPattern @("stdout_api_*.log", "api_*.log", "service_MonitorPage-Admin.log", "service_MonitorPage-Public.log")
    if ($apiLogs) {
        foreach ($log in $apiLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Worker logs
    Write-Host "[Worker Logs]" -ForegroundColor Yellow
    $workerLogs = Get-LogsMultiPattern @("stdout_worker_*.log", "worker_*.log", "unified_worker_*.log")
    if ($workerLogs) {
        foreach ($log in $workerLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Frontend logs
    Write-Host "[Frontend Logs]" -ForegroundColor Yellow
    $frontendLogs = Get-LogsMultiPattern @("frontend_*.log")
    if ($frontendLogs) {
        foreach ($log in $frontendLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Dev-Runner logs
    Write-Host "[Dev-Runner Logs]" -ForegroundColor Yellow
    $devRunnerLogs = Get-LogsMultiPattern @("dev_runner_command_listener*.log")
    if ($devRunnerLogs) {
        foreach ($log in $devRunnerLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Plan-runner logs (별도 디렉토리)
    Write-Host "[Plan-Runner Logs] ($planRunnerLogDir)" -ForegroundColor Yellow
    if ($useRedis) {
        $activeRunners = Get-ActivePlanRunners -LogDir $planRunnerLogDir
        if ($activeRunners.Count -gt 0) {
            Write-Host "  [Active Runners via Redis]" -ForegroundColor Cyan
            foreach ($runner in $activeRunners) {
                $shortId = $runner.ShortId
                $name    = $runner.DisplayName
                $logName = if ($runner.LogPath)    { [System.IO.Path]::GetFileName($runner.LogPath) }    else { "(no log)" }
                $strName = if ($runner.StreamPath) { [System.IO.Path]::GetFileName($runner.StreamPath) } else { "(no stream)" }
                Write-Host "  [$name#$shortId] runner=$($runner.RunnerId)"
                Write-Host "    log:    $logName"
                Write-Host "    stream: $strName"
            }
        } else {
            Write-Host "  (no active runners in Redis)" -ForegroundColor Gray
        }
    }
    if (Test-Path $planRunnerLogDir) {
        $anLogs = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
        if ($anLogs) {
            Write-Host "  [Recent Log Files]" -ForegroundColor DarkGray
            foreach ($log in $anLogs | Select-Object -First 5) {
                $size = "{0:N2} KB" -f ($log.Length / 1KB)
                $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                Write-Host "  $($log.Name) - $size - $date"
            }
        } else {
            Write-Host "  (none)" -ForegroundColor Gray
        }
    } else {
        Write-Host "  (dir not found)" -ForegroundColor Gray
    }

    Write-Host ""
    exit 0
}

# Get log files - check all patterns and return newest by LastWriteTime
function Get-LatestLogFileMultiPattern {
    param([string[]]$Prefixes)

    # Admin 모드: base logs/ 디렉토리도 탐색 (워커들이 logs/에 직접 기록)
    $searchDirs = @($LogDir)
    if ($Admin) {
        $baseLogDir = Join-Path $ProjectRoot "logs"
        if ($baseLogDir -ne $LogDir) { $searchDirs += $baseLogDir }
    }

    $allCandidates = @()
    foreach ($dir in $searchDirs) {
        foreach ($prefix in $Prefixes) {
            $pattern = Join-Path $dir "$prefix*.log"
            $found = Get-ChildItem $pattern -ErrorAction SilentlyContinue
            if ($found) { $allCandidates += $found }
        }
    }
    $nonEmpty = $allCandidates | Where-Object { $_.Length -gt 0 }
    $latest = if ($nonEmpty) {
        $nonEmpty | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    } else {
        $allCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($latest) { return $latest.FullName }
    return $null
}

# 다중 파일 반환 버전 — static 모드에서 최대 N개 파일 반환
# 선택 로직: LastWriteTime DESC 정렬 → 빈 파일(0바이트)은 포함 후 계속, 비어있지 않은 파일 만나면 포함 후 중단
# 반환: FullName 배열 (LastWriteTime ASC, 오래된→최신 출력용)
function Get-LatestLogFilesMultiPattern {
    param([string[]]$Prefixes, [int]$MaxCount = 3)

    $searchDirs = @($LogDir)
    if ($Admin) {
        $baseLogDir = Join-Path $ProjectRoot "logs"
        if ($baseLogDir -ne $LogDir) { $searchDirs += $baseLogDir }
    }

    $allCandidates = @()
    foreach ($dir in $searchDirs) {
        foreach ($prefix in $Prefixes) {
            $pattern = Join-Path $dir "$prefix*.log"
            $found = Get-ChildItem $pattern -ErrorAction SilentlyContinue
            if ($found) { $allCandidates += $found }
        }
    }
    if (-not $allCandidates) { return @() }

    $sorted = $allCandidates | Sort-Object LastWriteTime -Descending
    $result = @()
    foreach ($f in $sorted) {
        $result += $f
        if ($result.Count -ge $MaxCount) { break }
        if ($f.Length -gt 0) { break }  # 비어있지 않은 파일 만나면 중단
    }
    # 오래된→최신 순으로 재정렬 후 FullName 반환
    # LastWriteTime 오름차순(오래된→최신) 재정렬 후 FullName 반환
    # Sort-Object는 기본이 오름차순이므로 -Ascending 생략
    return ($result | Sort-Object LastWriteTime | ForEach-Object { $_.FullName })
}

# API 로그: 모든 후보에서 LastWriteTime이 가장 최신인 파일 선택
# Python 마이그레이션 후 API 앱은 LOG_DIR="logs" (하드코딩)에 api_*.log를 기록.
# Admin 모드: $LogDir=logs/admin/ (stdout_api_*, NSSM log) + logs/ (api_*)
# 운영 모드: $LogDir=logs/ (stdout_api_*, api_*, NSSM log) 모두 동일 디렉토리
$apiCandidates = @()
# 1) $LogDir 내 stdout_api_*, api_*
foreach ($prefix in @("stdout_api_*.log", "api_*.log")) {
    $found = Get-ChildItem (Join-Path $LogDir $prefix) -ErrorAction SilentlyContinue
    if ($found) { $apiCandidates += $found }
}
# 2) Admin 모드: base logs/ 디렉토리의 api_* (앱의 LOG_DIR가 logs/ 고정)
if ($Admin) {
    $baseLogDir = Join-Path $ProjectRoot "logs"
    if ($baseLogDir -ne $LogDir) {
        $found = Get-ChildItem (Join-Path $baseLogDir "api_*.log") -ErrorAction SilentlyContinue
        if ($found) { $apiCandidates += $found }
    }
}
# LastWriteTime이 가장 최신인 파일 선택
$apiLogFile = $apiCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($apiLogFile) { $apiLogFile = $apiLogFile.FullName }
$workerLogFile = Get-LatestLogFileMultiPattern @("stdout_worker_", "worker_", "unified_worker_")
$frontendLogFile = Get-LatestLogFileMultiPattern @("frontend_2")
$claudeWorkerLogFile = Get-LatestLogFileMultiPattern @("llm_worker_")
$videoDownloadWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_video_download_worker_", "video_download_worker_")
$crawlWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_crawl_", "crawl_worker_")

# Watchdog/Service 로그도 타임스탬프 파일명으로 전환됨 — 패턴 탐색으로 최신 파일 선택
$serviceRunnerLogFile = Get-LatestLogFileMultiPattern @("service_runner_")
$watchdogLogFile = Get-LatestLogFileMultiPattern @("watchdog_")
# unified_watchdog는 watchdog와 별도로 탐색
$unifiedWatchdogLogFile = Get-LatestLogFileMultiPattern @("unified_watchdog_")
# unified가 있으면 우선, 없으면 legacy watchdog 사용
if ($unifiedWatchdogLogFile) { $watchdogLogFile = $unifiedWatchdogLogFile }
$igWatchdogLogFile = $null  # 폐기됨
$claudeWatchdogLogFile = Get-LatestLogFileMultiPattern @("claude_watchdog_")
$videoDownloadWatchdogLogFile = Get-LatestLogFileMultiPattern @("video_download_watchdog_")
$crawlWatchdogLogFile = Get-LatestLogFileMultiPattern @("crawl_watchdog_")
$commandListenerWatchdogLogFile = Get-LatestLogFileMultiPattern @("command_listener_watchdog_")
$apiWatchdogLogFile = Get-LatestLogFileMultiPattern @("api_watchdog_")
$workerCommandListenerLogFile = Get-LatestLogFileMultiPattern @("worker_command_listener_")
$devRunnerLogFile = Get-LatestLogFileMultiPattern @("dev_runner_command_listener")
$mergeOrchestratorLogFile = Get-LatestLogFileMultiPattern @("merge-orchestrator_")
$cloudflaredLogFile = Get-LatestLogFileMultiPattern @("cloudflared_err", "cloudflared")

# Plan-runner 로그: wtools/common/logs/ 에서 최신 파일 ($planRunnerLogDir는 상단에서 이미 정의)
$planRunnerLogFile = $null
if (Test-Path $planRunnerLogDir) {
    $found = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "stream" } |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($found) { $planRunnerLogFile = $found.FullName }
}
$planRunnerStreamLogFile = $null
if (Test-Path $planRunnerLogDir) {
    $found = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-stream-*.log" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($found) { $planRunnerStreamLogFile = $found.FullName }
}

# Plan-runner 표시 이름 추출: "2026-02-25_smart-push-auto-rebase.md" → "smart-push"
function Get-PlanRunnerDisplayName {
    param([string]$PlanFile)
    if (-not $PlanFile) { return "unknown" }
    $basename = [System.IO.Path]::GetFileNameWithoutExtension($PlanFile)
    # 날짜 prefix 제거 (YYYY-MM-DD_ 패턴)
    $basename = $basename -replace '^\d{4}-\d{2}-\d{2}_', ''
    # 첫 2단어 (하이픈 구분) 추출
    $parts = $basename -split '-'
    if ($parts.Count -ge 2) {
        return "$($parts[0])-$($parts[1])"
    }
    return $parts[0]
}

# plan-runner 로그 파일명에서 식별자 추출
# plan-runner-{runner_id}-{YYYYMMDD-HHmmss}.log → "{runner_id}" (8자 hex)
# 구버전 plan-runner-{YYYYMMDD-HHmmss}.log → "{HHmmss}"
function Get-PlanRunnerFileId {
    param([string]$FileName)
    # 신규 형식: plan-runner-{8자hex}-YYYYMMDD-HHmmss.log → runner_id 추출
    if ($FileName -match 'plan-runner-([0-9a-f]{8})-\d{8}-\d{6}') { return $Matches[1] }
    # 구버전 형식: plan-runner-YYYYMMDD-HHmmss.log → HHmmss 추출
    if ($FileName -match 'plan-runner-\d{8}-(\d{6})') { return $Matches[1] }
    return "unknown"
}

# Redis에서 활성 plan-runner 목록 조회
function Test-RedisValue($val) {
    return ($val -and $val.Trim() -ne "" -and $val.Trim() -ne "(nil)")
}

function Get-ActivePlanRunners {
    param([string]$LogDir)
    $result = @()

    # Redis 연결 확인 (2초 타임아웃)
    $pingOut = & redis-cli -t 2 PING 2>$null
    if ($pingOut -ne "PONG") {
        return $result
    }

    # 활성 runner_id 목록 (2초 타임아웃)
    $runnerIds = & redis-cli -t 2 SMEMBERS "plan-runner:active_runners" 2>$null
    if (-not $runnerIds) { return $result }

    foreach ($rid in $runnerIds) {
        $rid = $rid.Trim()
        if (-not $rid) { continue }

        $logPath    = & redis-cli -t 2 GET "plan-runner:runners:${rid}:log_file_path" 2>$null
        $planFile   = & redis-cli -t 2 GET "plan-runner:runners:${rid}:plan_file"    2>$null
        $streamPath = & redis-cli -t 2 GET "plan-runner:runners:${rid}:stream_log_path" 2>$null
        $pidVal     = & redis-cli -t 2 GET "plan-runner:runners:${rid}:pid"          2>$null

        $logPath    = if (Test-RedisValue $logPath)    { $logPath.Trim()    } else { $null }
        $planFile   = if (Test-RedisValue $planFile)   { $planFile.Trim()   } else { $null }
        $streamPath = if (Test-RedisValue $streamPath) { $streamPath.Trim() } else { $null }
        $pidVal     = if (Test-RedisValue $pidVal)     { $pidVal.Trim()     } else { $null }

        $displayName = Get-PlanRunnerDisplayName -PlanFile ([System.IO.Path]::GetFileName($planFile))
        $shortId = $rid.Substring(0, [Math]::Min(4, $rid.Length))

        $result += @{
            RunnerId    = $rid
            ShortId     = $shortId
            DisplayName = $displayName
            LogPath     = $logPath
            StreamPath  = $streamPath
            PlanFile    = $planFile
            PID         = $pidVal
        }
    }
    return $result
}

# Redis 연결 여부 + 활성 runner 캐시 (초기화 시)
$useRedis = $false
$pingOut = & redis-cli PING 2>$null
if ($pingOut -eq "PONG") { $useRedis = $true }

# Check if log files are stale — 파일명 날짜(_YYYYMMDD_) 기반: 오늘 날짜 파일이면 항상 유효
function Test-StaleLogFile {
    param([string]$FilePath, [string]$ReferenceFile)

    if (-not $FilePath -or -not (Test-Path $FilePath)) { return $false }

    # 파일명에서 날짜 추출 (_YYYYMMDD_ 패턴)
    $fileName = Split-Path $FilePath -Leaf
    if ($fileName -match '_(\d{8})_') {
        return $matches[1] -ne (Get-Date).ToString("yyyyMMdd")
    }

    # 날짜 패턴 없는 파일: LastWriteTime fallback (1시간 기준)
    if (-not $ReferenceFile -or -not (Test-Path $ReferenceFile)) { return $false }
    $fileTime = (Get-Item $FilePath).LastWriteTime
    $refTime  = (Get-Item $ReferenceFile).LastWriteTime
    return ($refTime - $fileTime).TotalHours -gt 1
}

# Warn about potentially stale log files and exclude them — apiLogFile 유무와 무관하게 항상 실행
$timestampedLogs = @(
    @{ Name = "Worker"; Var = "workerLogFile" },
    @{ Name = "Claude Worker"; Var = "claudeWorkerLogFile" },
    @{ Name = "Video Download"; Var = "videoDownloadWorkerLogFile" },
    @{ Name = "Crawl Worker"; Var = "crawlWorkerLogFile" }
)

foreach ($log in $timestampedLogs) {
    $logFile = Get-Variable -Name $log.Var -ValueOnly -ErrorAction SilentlyContinue
    if ($logFile -and (Test-StaleLogFile $logFile $apiLogFile)) {
        Write-Host "[!] $($log.Name) log may be stale (from previous session)" -ForegroundColor Yellow
        Set-Variable -Name $log.Var -Value $null
    }
}

# Watchdog/Service 로그도 타임스탬프 기반으로 전환됨 — stale 체크 통일
$extraTimestampedLogs = @(
    @{ Name = "Watchdog"; Var = "watchdogLogFile" },
    @{ Name = "Claude-Watchdog"; Var = "claudeWatchdogLogFile" },
    @{ Name = "Video-DL-Watchdog"; Var = "videoDownloadWatchdogLogFile" },
    @{ Name = "Crawl-Watchdog"; Var = "crawlWatchdogLogFile" },
    @{ Name = "Service Runner"; Var = "serviceRunnerLogFile" },
    @{ Name = "CMD-Watchdog"; Var = "commandListenerWatchdogLogFile" },
    @{ Name = "API-Watchdog"; Var = "apiWatchdogLogFile" }
)

foreach ($log in $extraTimestampedLogs) {
    $logFile = Get-Variable -Name $log.Var -ValueOnly -ErrorAction SilentlyContinue
    if ($logFile -and (Test-StaleLogFile $logFile $apiLogFile)) {
        Write-Host "[!] $($log.Name) log may be stale (from previous session)" -ForegroundColor Yellow
        Set-Variable -Name $log.Var -Value $null
    }
}

# Public 모드: 워커/watchdog/dev-runner 로그 제외 (Admin 아닐 때)
if (-not $Admin) {
    $workerLogFile = $null
    $claudeWorkerLogFile = $null
    $videoDownloadWorkerLogFile = $null
    $crawlWorkerLogFile = $null
    $watchdogLogFile = $null
    $claudeWatchdogLogFile = $null
    $videoDownloadWatchdogLogFile = $null
    $crawlWatchdogLogFile = $null
    $commandListenerWatchdogLogFile = $null
    $apiWatchdogLogFile = $null
    $workerCommandListenerLogFile = $null
    $devRunnerLogFile = $null
    $planRunnerLogFile = $null
    $planRunnerStreamLogFile = $null
}

# 오늘 날짜 plan-runner 로그 최대 5개 표시 (Redis 미연결/활성 runner 없을 때 fallback)
function Show-TodayPlanRunnerLogs {
    param([int]$TailLines)
    if (-not (Test-Path $planRunnerLogDir)) {
        Write-Host "[PR] (plan-runner log dir not found)" -ForegroundColor Gray
        return
    }
    $todayStr = (Get-Date).ToString("yyyyMMdd")
    $todayFiles = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "stream" -and $_.Name -match $todayStr } |
        Sort-Object Name -Descending | Select-Object -First 5
    if (-not $todayFiles) {
        # 오늘 날짜 없으면 최신 1개 폴백
        $todayFiles = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-*.log" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch "stream" } |
            Sort-Object Name -Descending | Select-Object -First 1
    }
    foreach ($lf in ($todayFiles | Sort-Object Name)) {
        $prFileId = Get-PlanRunnerFileId -FileName $lf.Name
        Show-LogContent -FilePath $lf.FullName -Label "PR:$prFileId" -Color White -TailLines $TailLines
        # 동일 runner ID로 stream 파일 탐색
        $streamFile = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-stream-*${prFileId}*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        if (-not $streamFile) {
            # ID 매칭 없으면 같은 날짜 최신 stream 파일
            $streamFile = Get-ChildItem -Path $planRunnerLogDir -Filter "plan-runner-stream-*${todayStr}*.log" -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | Select-Object -First 1
        }
        if ($streamFile) {
            Show-LogContent -FilePath $streamFile.FullName -Label "PS:$prFileId" -Color DarkGray -TailLines ([Math]::Min($TailLines, 20))
        }
    }
}

# Show log content function
# $FilePath: 단일 파일 (하위 호환)
# $FilePaths: 다중 파일 배열 (오래된→최신 순 전달 권장)
function Show-LogContent {
    param(
        [string]$FilePath,
        [string[]]$FilePaths,
        [string]$Label,
        [ConsoleColor]$Color,
        [int]$TailLines
    )

    # 하위 호환: $FilePath가 주어지면 $FilePaths로 병합
    if ($FilePath) {
        if ($FilePaths) { $FilePaths = @($FilePath) + $FilePaths }
        else { $FilePaths = @($FilePath) }
    }

    # 유효 파일만 필터
    $validPaths = @($FilePaths | Where-Object { $_ -and (Test-Path $_) })

    if ($validPaths.Count -eq 0) {
        Write-Host "[$Label] Log file not found" -ForegroundColor Gray
        return
    }

    # 헤더
    Write-Host "`n========================================" -ForegroundColor $Color
    Write-Host "  $Label Log" -ForegroundColor $Color
    if ($validPaths.Count -eq 1) {
        Write-Host "  File: $(Split-Path $validPaths[0] -Leaf)" -ForegroundColor $Color
    } else {
        Write-Host "  Files ($($validPaths.Count)): $(($validPaths | ForEach-Object { Split-Path $_ -Leaf }) -join ', ')" -ForegroundColor $Color
    }
    Write-Host "========================================" -ForegroundColor $Color
    Write-Host ""

    $multiFile = $validPaths.Count -gt 1

    foreach ($fp in $validPaths) {
        if ($multiFile) {
            Write-Host "--- $(Split-Path $fp -Leaf) ---" -ForegroundColor DarkGray
        }
        $content = Get-Content $fp -Tail $TailLines -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($content) {
            foreach ($line in $content) {
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
            Write-Host "(no content)" -ForegroundColor Gray
        }
    }
}

# Real-time log tail function (single file)
function Start-LogTail {
    param(
        [string]$FilePath,
        [string]$Prefix
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[!] Log file not found: $Prefix" -ForegroundColor Red
        return
    }

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Real-time Log: $Prefix" -ForegroundColor Cyan
    Write-Host "  File: $(Split-Path $FilePath -Leaf)" -ForegroundColor Cyan
    Write-Host "  Exit: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Use PowerShell Get-Content -Wait
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

# Real-time combined log tail (using FileSystemWatcher instead of Start-Job for UTF-8 support)
function Start-CombinedLogTail {
    param(
        [string]$ApiLog,
        [string]$WorkerLog,
        [string]$FrontendLog,
        [string]$ClaudeWorkerLog,
        [string]$VideoDownloadLog,
        [string]$CrawlWorkerLog,
        [string]$ServiceRunnerLog,
        [string]$WatchdogLog,
        [string]$ClaudeWatchdogLog,
        [string]$VideoDownloadWatchdogLog,
        [string]$CrawlWatchdogLog,
        [string]$CommandListenerWatchdogLog,
        [string]$ApiWatchdogLog,
        [string]$DevRunnerLog,
        [string]$CloudflaredLog
    )

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Real-time Combined Log" -ForegroundColor Cyan
    Write-Host "  Exit: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Log source configuration: Name -> (FilePath, Color, InitialTailLines)
    $logConfig = [ordered]@{
        "SERVICE"     = @{ Path = $ServiceRunnerLog;  Color = "DarkCyan";    Tail = 3 }
        "TUNNEL"      = @{ Path = $CloudflaredLog;    Color = "DarkGray";    Tail = 3 }
        "API"         = @{ Path = $ApiLog;            Color = "Cyan";        Tail = 5 }
        "WORKER"      = @{ Path = $WorkerLog;         Color = "Magenta";     Tail = 5 }
        "LLM"         = @{ Path = $ClaudeWorkerLog;   Color = "Blue";        Tail = 3 }
        "VIDEO-DL"    = @{ Path = $VideoDownloadLog;  Color = "DarkGreen";   Tail = 5 }
        "CRAWL"       = @{ Path = $CrawlWorkerLog;    Color = "DarkBlue";    Tail = 5 }
        "FRONTEND"    = @{ Path = $FrontendLog;       Color = "Green";       Tail = 3 }
        "WATCHDOG"    = @{ Path = $WatchdogLog;       Color = "DarkYellow";  Tail = 2 }
        "CLAUDE-WD"   = @{ Path = $ClaudeWatchdogLog; Color = "DarkYellow";  Tail = 2 }
        "VIDEO-DL-WD" = @{ Path = $VideoDownloadWatchdogLog; Color = "DarkYellow"; Tail = 2 }
        "CRAWL-WD"    = @{ Path = $CrawlWatchdogLog;  Color = "DarkYellow";  Tail = 2 }
        "CMD-WD"      = @{ Path = $CommandListenerWatchdogLog; Color = "DarkYellow"; Tail = 2 }
        "API-WD"      = @{ Path = $ApiWatchdogLog;          Color = "DarkYellow"; Tail = 3 }
        "CMD-LISTENER" = @{ Path = $workerCommandListenerLogFile; Color = "DarkCyan"; Tail = 5 }
        "DEV-RUNNER"  = @{ Path = $DevRunnerLog;           Color = "DarkCyan";    Tail = 10 }
        "MERGE-ORCH"  = @{ Path = $mergeOrchestratorLogFile; Color = "Cyan";       Tail = 10 }
    }

    # Plan-runner 소스 동적 추가 (Redis 활성 runner 기반)
    if ($useRedis) {
        $activeRunners = Get-ActivePlanRunners -LogDir $planRunnerLogDir
        if ($activeRunners.Count -gt 0) {
            foreach ($runner in $activeRunners) {
                $pidSuffix = if ($runner.PID) { "|PID:$($runner.PID)" } else { "" }
                $prKey = "PR:$($runner.DisplayName)#$($runner.ShortId)$pidSuffix"
                $psKey = "PS:$($runner.DisplayName)#$($runner.ShortId)$pidSuffix"
                $psPath = if ($runner.StreamPath) { $runner.StreamPath } else { $planRunnerStreamLogFile }
                $logConfig[$prKey] = @{ Path = $runner.LogPath; Color = "White";    Tail = 10 }
                $logConfig[$psKey] = @{ Path = $psPath;         Color = "DarkGray"; Tail = 5  }
            }
        } else {
            # 활성 runner 없음 — 폴백: 최신 파일 1개 (파일명 타임스탬프 식별자 사용)
            $prFileId = Get-PlanRunnerFileId -FileName ([System.IO.Path]::GetFileName($planRunnerLogFile))
            $logConfig["PR:$prFileId"] = @{ Path = $planRunnerLogFile;       Color = "White";    Tail = 10 }
            $logConfig["PS:$prFileId"] = @{ Path = $planRunnerStreamLogFile; Color = "DarkGray"; Tail = 5  }
        }
    } else {
        # Redis 없음 — 폴백: 최신 파일 1개 (파일명 타임스탬프 식별자 사용)
        $prFileId = Get-PlanRunnerFileId -FileName ([System.IO.Path]::GetFileName($planRunnerLogFile))
        $logConfig["PR:$prFileId"] = @{ Path = $planRunnerLogFile;       Color = "White";    Tail = 10 }
        $logConfig["PS:$prFileId"] = @{ Path = $planRunnerStreamLogFile; Color = "DarkGray"; Tail = 5  }
    }

    # Sources that only show errors/warnings (suppress verbose output)
    $errorOnlySources = @("FRONTEND")

    # Track file positions
    $filePositions = @{}
    $logFiles = @{}
    $logColors = @{}

    foreach ($source in $logConfig.Keys) {
        $config = $logConfig[$source]
        $filePath = $config.Path

        if ($filePath -and (Test-Path $filePath)) {
            $logFiles[$source] = $filePath
            $logColors[$source] = $config.Color

            $fileItem = Get-Item $filePath
            $lastWrite = $fileItem.LastWriteTime.Date
            if ($lastWrite -eq (Get-Date).Date) {
                # 오늘 수정된 파일: 초기 tail 표시
                $filePositions[$source] = $fileItem.Length
                $initLines = Get-Content $filePath -Tail $config.Tail -Encoding UTF8 -ErrorAction SilentlyContinue
                foreach ($line in $initLines) {
                    # Error-only sources: skip non-error lines
                    if ($errorOnlySources -contains $source) {
                        if ($line -notmatch "ERROR|CRITICAL|Exception|WARN|error|fail|ERR_|TypeError|ReferenceError|SyntaxError") { continue }
                    }
                    Write-Host "[$source] $line" -ForegroundColor $config.Color
                }
            } else {
                # 오래된 파일: 초기 표시 스킵, 파일 끝으로 이동
                Write-Host "[$source] (waiting for new logs...)" -ForegroundColor DarkGray
                $filePositions[$source] = $fileItem.Length
            }
        }
    }

    if ($logFiles.Count -eq 0) {
        Write-Host "[!] No log files to follow." -ForegroundColor Red
        return
    }

    Write-Host "`n--- Following $($logFiles.Count) log sources... ---`n" -ForegroundColor DarkGray

    # Track current log file names for detecting new files
    $logFileNames = @{}
    foreach ($source in $logFiles.Keys) {
        $logFileNames[$source] = Split-Path $logFiles[$source] -Leaf
    }

    # Define timestamped log patterns for auto-refresh (multiple patterns per source)
    $timestampedLogPatterns = @{
        "API"         = @("stdout_api_*.log", "api_*.log")
        "WORKER"      = @("stdout_worker_*.log", "worker_*.log", "unified_worker_*.log")
        "LLM"         = @("llm_worker_*.log")
        "VIDEO-DL"    = @("stdout_video_download_worker_*.log", "video_download_worker_*.log")
        "CRAWL"       = @("stdout_crawl_*.log", "crawl_worker_*.log")
        "FRONTEND"    = @("frontend_2*.log")
        "SERVICE"     = @("service_runner_*.log")
        "WATCHDOG"    = @("watchdog_*.log", "unified_watchdog_*.log")
        "CLAUDE-WD"   = @("claude_watchdog_*.log")
        "VIDEO-DL-WD" = @("video_download_watchdog_*.log")
        "CRAWL-WD"    = @("crawl_watchdog_*.log")
        "CMD-WD"      = @("command_listener_watchdog_*.log")
        "API-WD"      = @("api_watchdog_*.log")
        "CMD-LISTENER" = @("worker_command_listener_*.log")
        "DEV-RUNNER"  = @("dev_runner_command_listener*.log")
        "MERGE-ORCH"  = @("merge-orchestrator_*.log")
        "TUNNEL"      = @("cloudflared_err_*.log", "cloudflared_err-*.log", "cloudflared_*.log")
    }

    # Admin 전용 소스 — Production에서 제외 (Worker 로그는 logs/ 또는 logs/admin/에 기록됨)
    $devOnlySources = @("WORKER", "LLM", "VIDEO-DL", "CRAWL",
                         "CLAUDE-WD", "VIDEO-DL-WD", "CRAWL-WD", "CMD-WD", "API-WD",
                         "WATCHDOG", "CMD-LISTENER", "DEV-RUNNER", "MERGE-ORCH", "PLAN-RUNNER", "PR-STREAM")
    if (-not $Admin) {
        foreach ($source in $devOnlySources) {
            $logConfig.Remove($source)
            $timestampedLogPatterns.Remove($source)
            $logFiles.Remove($source)
            $logColors.Remove($source)
            $filePositions.Remove($source)
        }
        # PR:xxx / PS:xxx 형태 동적 plan-runner key 제거 (Admin 아닐 때)
        $prKeys = @($logConfig.Keys | Where-Object { $_ -like "PR:*" -or $_ -like "PS:*" })
        foreach ($key in $prKeys) {
            $logConfig.Remove($key)
            $logFiles.Remove($key)
            $logColors.Remove($key)
            $filePositions.Remove($key)
        }
    }

    # Helper to find latest log from multiple patterns
    # Admin 모드일 때 base logs/ 디렉토리도 탐색 (API 앱의 LOG_DIR가 logs/ 고정)
    function Get-LatestLogFromPatterns {
        param([string[]]$Patterns, [switch]$IncludeEmpty)
        $searchDirs = @($LogDir)
        if ($Admin) {
            $baseLogDir = Join-Path $ProjectRoot "logs"
            if ($baseLogDir -ne $LogDir) { $searchDirs += $baseLogDir }
        }
        $allCandidates = @()
        foreach ($dir in $searchDirs) {
            foreach ($pattern in $Patterns) {
                $found = Get-ChildItem -Path $dir -Filter $pattern -ErrorAction SilentlyContinue
                if ($found) { $allCandidates += $found }
            }
        }
        # LastWriteTime 기준 최신 파일
        # $IncludeEmpty=true: 파일명 기준 새 파일 감지용 (0바이트도 포함)
        # $IncludeEmpty=false(기본): 초기 파일 선택용 — 0바이트 우선 제외
        if (-not $IncludeEmpty) {
            $nonEmpty = $allCandidates | Where-Object { $_.Length -gt 0 }
            if ($nonEmpty) {
                return $nonEmpty | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            }
        }
        return $allCandidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }

    # Plan-runner 로그 전용 패턴 (폴백 전용 — Redis 미연결 시)
    $planRunnerLogPatterns = @{
        "PLAN-RUNNER" = @{ Dir = $planRunnerLogDir; Filter = "plan-runner-*.log"; Exclude = "stream" }
        "PR-STREAM" = @{ Dir = $planRunnerLogDir; Filter = "plan-runner-stream-*.log"; Exclude = $null }
    }

    # Redis runner 재조회 타이머
    $lastRunnerRefresh = [DateTime]::MinValue
    $runnerRefreshInterval = 10  # 초

    # 종료 runner grace period 추적 (키 → 감지 시각)
    $staleDetectedAt = @{}

    # [진단] PR:/PS: 키 최초 출력 여부 (1회성)
    $diagPrinted = $false

    try {
        while ($true) {
            # Plan-runner 로그 자동 감지
            if ($useRedis) {
                # Redis 기반: 10초마다 active_runners 재조회
                $now = [DateTime]::Now
                if (($now - $lastRunnerRefresh).TotalSeconds -ge $runnerRefreshInterval) {
                    $lastRunnerRefresh = $now
                    $currentRunners = Get-ActivePlanRunners -LogDir $planRunnerLogDir
                    # 폴백 키(#없는 PR:/PS:) → Redis 키로 전환 시 정리
                    $fallbackKeys = @($logFiles.Keys | Where-Object { ($_ -like "PR:*" -or $_ -like "PS:*") -and $_ -notlike "*#*" })
                    foreach ($fk in $fallbackKeys) {
                        $logFiles.Remove($fk)
                        $logColors.Remove($fk)
                        $filePositions.Remove($fk)
                        $logFileNames.Remove($fk)
                    }

                    # 현재 활성 runner 키 수집 (종료된 runner 정리용)
                    $activeKeys = @{}
                    foreach ($runner in $currentRunners) {
                        $pidSuffix = if ($runner.PID) { "|PID:$($runner.PID)" } else { "" }
                        $prKey = "PR:$($runner.DisplayName)#$($runner.ShortId)$pidSuffix"
                        $psKey = "PS:$($runner.DisplayName)#$($runner.ShortId)$pidSuffix"
                        $activeKeys[$prKey] = $true
                        $activeKeys[$psKey] = $true

                        if (-not $logConfig.ContainsKey($prKey)) {
                            # 새 runner 감지
                            Write-Host "[$prKey] === New runner detected: $($runner.RunnerId) ===" -ForegroundColor Green
                            $logConfig[$prKey] = @{ Path = $runner.LogPath;    Color = "White";    Tail = 10 }
                            $logConfig[$psKey] = @{ Path = $runner.StreamPath; Color = "DarkGray"; Tail = 5  }
                            if ($runner.LogPath) {
                                # LogPath가 유효한 경우에만 $logFiles에 등록 (null이면 다음 refresh에서 재시도)
                                $logFiles[$prKey]      = $runner.LogPath
                                $logFileNames[$prKey]  = [System.IO.Path]::GetFileName($runner.LogPath)
                                $logColors[$prKey]     = "White"
                                $filePositions[$prKey] = 0
                            } else {
                                Write-Host "[$prKey] === LogPath null — 다음 refresh에서 재시도 ===" -ForegroundColor DarkGray
                            }
                        } elseif ((-not $logFiles[$prKey] -or ($logFiles[$prKey] -and -not (Test-Path $logFiles[$prKey]))) -and $runner.LogPath) {
                            # null 경로 또는 파일 미존재 → 유효 경로로 복구 (race condition 대응)
                            Write-Host "[$prKey] === Log path resolved: $([System.IO.Path]::GetFileName($runner.LogPath)) ===" -ForegroundColor Green
                            $logConfig[$prKey].Path = $runner.LogPath
                            $logFiles[$prKey]      = $runner.LogPath
                            $logFileNames[$prKey]  = [System.IO.Path]::GetFileName($runner.LogPath)
                            $filePositions[$prKey] = 0
                        } else {
                            Write-Host "[$prKey] === SKIP(already tracked: $($logFiles[$prKey])) ===" -ForegroundColor DarkGray
                        }
                        # StreamPath 지연 등록: 초기에 null이었거나 파일 미존재였지만 이후 설정된 경우
                        if ($runner.StreamPath -and (-not $logFiles.ContainsKey($psKey) -or ($logFiles.ContainsKey($psKey) -and $logFiles[$psKey] -and -not (Test-Path $logFiles[$psKey])))) {
                            Write-Host "[$psKey] === Stream log detected: $([System.IO.Path]::GetFileName($runner.StreamPath)) ===" -ForegroundColor Green
                            $logConfig[$psKey] = @{ Path = $runner.StreamPath; Color = "DarkGray"; Tail = 5  }
                            $logFiles[$psKey]      = $runner.StreamPath
                            $logFileNames[$psKey]  = [System.IO.Path]::GetFileName($runner.StreamPath)
                            $logColors[$psKey]     = "DarkGray"
                            $filePositions[$psKey] = 0
                        }
                    }
                    # 종료된 runner 정리 (30초 grace period — 마지막 버퍼 flush 대기)
                    $staleKeys = @($logFiles.Keys | Where-Object { ($_ -like "PR:*#*" -or $_ -like "PS:*#*") -and -not $activeKeys.ContainsKey($_) })
                    foreach ($sk in $staleKeys) {
                        if (-not $staleDetectedAt.ContainsKey($sk)) {
                            $staleDetectedAt[$sk] = [DateTime]::Now
                        }
                    }
                    # grace period 만료된 키만 실제 삭제
                    $expiredKeys = @($staleDetectedAt.Keys | Where-Object {
                        ([DateTime]::Now - $staleDetectedAt[$_]).TotalSeconds -ge 30
                    })
                    foreach ($ek in $expiredKeys) {
                        $logFiles.Remove($ek)
                        $logColors.Remove($ek)
                        $filePositions.Remove($ek)
                        $logFileNames.Remove($ek)
                        $logConfig.Remove($ek)
                        $staleDetectedAt.Remove($ek)
                    }
                    # 다시 active가 된 키는 stale 추적에서 제거
                    $revivedKeys = @($staleDetectedAt.Keys | Where-Object { $activeKeys.ContainsKey($_) })
                    foreach ($rk in $revivedKeys) {
                        $staleDetectedAt.Remove($rk)
                    }
                }
            } else {
                # 폴백: 최신 파일 1개 추적 — 파일명 타임스탬프 기반 key 사용
                $cfg = $planRunnerLogPatterns["PLAN-RUNNER"]
                if (Test-Path $cfg.Dir) {
                    $candidates = Get-ChildItem -Path $cfg.Dir -Filter $cfg.Filter -ErrorAction SilentlyContinue
                    if ($cfg.Exclude) { $candidates = $candidates | Where-Object { $_.Name -notmatch $cfg.Exclude } }
                    $latest = $candidates | Sort-Object Name -Descending | Select-Object -First 1
                    if ($latest) {
                        $newFileId = Get-PlanRunnerFileId -FileName $latest.Name
                        $newPrKey  = "PR:$newFileId"
                        $newPsKey  = "PS:$newFileId"
                        # 현재 추적 중인 PR: key 탐색
                        $currentPrKey = (@($logFiles.Keys) | Where-Object { $_ -like "PR:*" -and $_ -notlike "PR:*#*" } | Select-Object -First 1)
                        if ($currentPrKey -ne $newPrKey) {
                            $oldId = if ($currentPrKey) { $currentPrKey } else { "(없음)" }
                            Write-Host "[$newPrKey] === Switched: $oldId → $newPrKey ($($latest.Name)) ===" -ForegroundColor Yellow
                            # 이전 key 제거
                            if ($currentPrKey) {
                                $oldPsKey = $currentPrKey -replace '^PR:', 'PS:'
                                $logFiles.Remove($currentPrKey)
                                $logFiles.Remove($oldPsKey)
                                $logFileNames.Remove($currentPrKey)
                                $logFileNames.Remove($oldPsKey)
                                $logColors.Remove($currentPrKey)
                                $logColors.Remove($oldPsKey)
                                $filePositions.Remove($currentPrKey)
                                $filePositions.Remove($oldPsKey)
                            }
                            # 새 key 추가
                            $logFiles[$newPrKey]      = $latest.FullName
                            $logFileNames[$newPrKey]  = $latest.Name
                            $logColors[$newPrKey]     = "White"
                            $filePositions[$newPrKey] = 0
                            # stream 파일도 탐색
                            $cfgS = $planRunnerLogPatterns["PR-STREAM"]
                            $latestS = Get-ChildItem -Path $cfgS.Dir -Filter $cfgS.Filter -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
                            if ($latestS) {
                                $logFiles[$newPsKey]      = $latestS.FullName
                                $logFileNames[$newPsKey]  = $latestS.Name
                                $logColors[$newPsKey]     = "DarkGray"
                                $filePositions[$newPsKey] = 0
                            }
                        }
                    }
                }
            }

            # Check for new log files (service restart detection)
            # 파일명 비교(새 파일 감지)는 0바이트 포함 전체 후보 중 최신으로 — 새 세션 파일이 처음엔 0바이트여도 전환 감지 필요
            foreach ($source in @($timestampedLogPatterns.Keys)) {
                $patterns = $timestampedLogPatterns[$source]
                $latestLog = Get-LatestLogFromPatterns $patterns -IncludeEmpty

                if ($latestLog) {
                    $currentName = $logFileNames[$source]
                    if ($latestLog.Name -ne $currentName) {
                        # New log file detected
                        Write-Host "[$source] === Switched to new log: $($latestLog.Name) ===" -ForegroundColor Yellow
                        $logFiles[$source] = $latestLog.FullName
                        $logFileNames[$source] = $latestLog.Name
                        $filePositions[$source] = 0
                    }
                } elseif (-not $logFiles.ContainsKey($source)) {
                    # Log file appeared for the first time
                    if ($latestLog) {
                        Write-Host "[$source] === New log detected: $($latestLog.Name) ===" -ForegroundColor Green
                        $logFiles[$source] = $latestLog.FullName
                        $logFileNames[$source] = $latestLog.Name
                        # Null-safe color assignment
                        $color = $logConfig[$source].Color
                        $logColors[$source] = if ($null -ne $color) { $color } else { "White" }
                        $filePositions[$source] = 0
                    }
                }
            }

            # [진단] PR:/PS: 키 최초 출력 — 어떤 키가 등록됐는지 확인
            if (-not $diagPrinted) {
                $prPsKeys = @($logFiles.Keys | Where-Object { $_ -like "PR:*" -or $_ -like "PS:*" })
                if ($prPsKeys.Count -gt 0) {
                    Write-Host "[DIAG] 등록된 PR:/PS: 키 목록:" -ForegroundColor DarkGray
                    foreach ($k in $prPsKeys) {
                        Write-Host "[DIAG]   $k → $($logFiles[$k])" -ForegroundColor DarkGray
                    }
                    $diagPrinted = $true
                }
            }

            foreach ($source in @($logFiles.Keys)) {
                $filePath = $logFiles[$source]
                $item = Get-Item $filePath -ErrorAction SilentlyContinue
                if (-not $item) { continue }

                $currentSize = $item.Length

                if ($currentSize -gt $filePositions[$source]) {
                    # Read new content using StreamReader for proper UTF-8
                    $stream = [System.IO.FileStream]::new($filePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    $stream.Seek($filePositions[$source], [System.IO.SeekOrigin]::Begin) | Out-Null
                    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)

                    while ($null -ne ($line = $reader.ReadLine())) {
                        # Error-only sources: skip non-error lines
                        if ($errorOnlySources -contains $source) {
                            if ($line -notmatch "ERROR|CRITICAL|Exception|WARN|error|fail|ERR_|TypeError|ReferenceError|SyntaxError") { continue }
                        }

                        # Get base color for this source (null-safe)
                        $sourceColor = if ($null -ne $logColors[$source]) { $logColors[$source] } else { "White" }

                        # Override color for errors/warnings
                        if ($line -match "ERROR|CRITICAL|Exception") {
                            $sourceColor = "Red"
                        } elseif ($line -match "WARNING|WARN") {
                            $sourceColor = "Yellow"
                        }

                        Write-Host "[$source] $line" -ForegroundColor $sourceColor
                    }

                    $filePositions[$source] = $stream.Position
                    $reader.Close()
                    $stream.Close()
                }
            }
            Start-Sleep -Milliseconds 200
        }
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
}

# Main logic
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Log Viewer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Real-time follow mode
if ($Follow) {
    switch ($Target) {
        "api" {
            Start-LogTail -FilePath $apiLogFile -Prefix "API"
        }
        "worker" {
            if (-not $Admin) {
                Write-Host "[!] Worker 로그는 Admin 모드에서만 사용 가능합니다. (-Admin 스위치를 추가하세요)" -ForegroundColor Red
            } else {
                Start-LogTail -FilePath $workerLogFile -Prefix "Worker"
            }
        }
        "frontend" {
            Start-LogTail -FilePath $frontendLogFile -Prefix "Frontend"
        }
        "watchdog" {
            if (-not $Admin) {
                Write-Host "[!] Watchdog 로그는 Admin 모드에서만 사용 가능합니다. (-Admin 스위치를 추가하세요)" -ForegroundColor Red
            } else {
                Start-CombinedLogTail `
                    -WatchdogLog $watchdogLogFile `
                    -ClaudeWatchdogLog $claudeWatchdogLogFile `
                    -VideoDownloadWatchdogLog $videoDownloadWatchdogLogFile `
                    -CrawlWatchdogLog $crawlWatchdogLogFile `
                    -CommandListenerWatchdogLog $commandListenerWatchdogLogFile `
                    -ApiWatchdogLog $apiWatchdogLogFile
            }
        }
        default {
            Start-CombinedLogTail `
                -ApiLog $apiLogFile `
                -WorkerLog $workerLogFile `
                -FrontendLog $frontendLogFile `
                -ClaudeWorkerLog $claudeWorkerLogFile `
                -VideoDownloadLog $videoDownloadWorkerLogFile `
                -CrawlWorkerLog $crawlWorkerLogFile `
                -ServiceRunnerLog $serviceRunnerLogFile `
                -WatchdogLog $watchdogLogFile `
                -ClaudeWatchdogLog $claudeWatchdogLogFile `
                -VideoDownloadWatchdogLog $videoDownloadWatchdogLogFile `
                -CrawlWatchdogLog $crawlWatchdogLogFile `
                -CommandListenerWatchdogLog $commandListenerWatchdogLogFile `
                -ApiWatchdogLog $apiWatchdogLogFile `
                -DevRunnerLog $devRunnerLogFile `
                -CloudflaredLog $cloudflaredLogFile
        }
    }
} else {
    # Static log display
    switch ($Target) {
        "api" {
            Show-LogContent -FilePath $apiLogFile -Label "API Server" -Color Cyan -TailLines $Lines
        }
        "worker" {
            if (-not $Admin) {
                Write-Host "[!] Worker 로그는 Admin 모드에서만 사용 가능합니다. (-Admin 스위치를 추가하세요)" -ForegroundColor Red
            } else {
                Show-LogContent -FilePath $workerLogFile -Label "Worker" -Color Magenta -TailLines $Lines
            }
        }
        "frontend" {
            Show-LogContent -FilePath $frontendLogFile -Label "Frontend" -Color Green -TailLines $Lines
        }
        "watchdog" {
            if (-not $Admin) {
                Write-Host "[!] Watchdog 로그는 Admin 모드에서만 사용 가능합니다. (-Admin 스위치를 추가하세요)" -ForegroundColor Red
            } else {
                Show-LogContent -FilePath $watchdogLogFile            -Label "WATCHDOG"  -Color DarkYellow -TailLines $Lines
                Show-LogContent -FilePath $claudeWatchdogLogFile      -Label "CLAUDE-WD" -Color DarkYellow -TailLines $Lines
                Show-LogContent -FilePath $videoDownloadWatchdogLogFile -Label "VIDEO-DL-WD" -Color DarkYellow -TailLines $Lines
                Show-LogContent -FilePath $crawlWatchdogLogFile       -Label "CRAWL-WD"  -Color DarkYellow -TailLines $Lines
                Show-LogContent -FilePath $commandListenerWatchdogLogFile -Label "CMD-WD" -Color DarkYellow -TailLines $Lines
                Show-LogContent -FilePath $apiWatchdogLogFile         -Label "API-WD"    -Color DarkYellow -TailLines $Lines
            }
        }
        default {
            $apiLogFiles = Get-LatestLogFilesMultiPattern @("stdout_api_", "api_")
            Show-LogContent -FilePaths $apiLogFiles -Label "API Server" -Color Cyan -TailLines $Lines
            if ($Admin) {
                $workerLogFiles = Get-LatestLogFilesMultiPattern @("stdout_worker_", "worker_", "unified_worker_")
                Show-LogContent -FilePaths $workerLogFiles -Label "Worker" -Color Magenta -TailLines $Lines
                $claudeWorkerLogFiles = Get-LatestLogFilesMultiPattern @("llm_worker_")
                Show-LogContent -FilePaths $claudeWorkerLogFiles -Label "LLM (Claude Worker)" -Color Blue -TailLines $Lines
                # Plan-runner 로그: Redis 활성 runner 또는 오늘 날짜 파일 최대 5개 표시
                if ($useRedis) {
                    $activeRunners = Get-ActivePlanRunners -LogDir $planRunnerLogDir
                    if ($activeRunners.Count -gt 0) {
                        foreach ($runner in $activeRunners) {
                            $label = "PR:$($runner.DisplayName)#$($runner.ShortId)"
                            Show-LogContent -FilePath $runner.LogPath -Label $label -Color White -TailLines $Lines
                            if ($runner.StreamPath) {
                                Show-LogContent -FilePath $runner.StreamPath -Label "PS:$($runner.DisplayName)#$($runner.ShortId)" -Color DarkGray -TailLines ([Math]::Min($Lines, 20))
                            }
                        }
                    } else {
                        # 활성 runner 없음 — 오늘 날짜 파일 최대 5개 표시
                        Show-TodayPlanRunnerLogs -TailLines $Lines
                    }
                } else {
                    # Redis 미연결 — 오늘 날짜 파일 최대 5개 표시
                    Show-TodayPlanRunnerLogs -TailLines $Lines
                }
            }
            $frontendLogFiles = Get-LatestLogFilesMultiPattern @("frontend_2")
            Show-LogContent -FilePaths $frontendLogFiles -Label "Frontend" -Color Green -TailLines $Lines
        }
    }
}

Write-Host ""
