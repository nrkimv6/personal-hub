# Monitor Page - Log Viewer Script
# View logs for API server, worker, and frontend in real-time

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "api", "worker", "frontend", "list", "watchdog", "devrunner", "dev-runner")]
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
    [switch]$Cleanup,  # Filter output to show only runner cleanup events

    [Parameter()]
    [switch]$Help
)

# Set console output encoding to UTF-8 for Korean support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

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
    .\logs.ps1 [target] [-Lines N] [-Follow] [-Cleanup] [-Help]

Targets:
    all       Show API, Worker, Frontend, and Dev-Runner logs together (default)
    api       Show API server logs only
    worker    Show Worker logs only
    frontend  Show Frontend logs only
    devrunner Show Dev-Runner listener logs only
    dev-runner Alias for devrunner
    list      List available log files

Options:
    -Lines N    Number of lines to show (default: 50)
    -Follow     Follow logs in real-time (like tail -f)
    -Cleanup    Filter output to show only runner cleanup/정리 events
    -Help       Show this help message

Examples:
    .\logs.ps1                           # Show last 50 lines of all logs
    .\logs.ps1 api                       # Show API logs only
    .\logs.ps1 devrunner -Follow         # Follow dev-runner logs in real-time
    .\logs.ps1 devrunner -Follow -Cleanup  # Show only cleanup events in real-time
    .\logs.ps1 worker -Lines 100         # Show last 100 lines of worker logs
    .\logs.ps1 all -Follow               # Follow all logs in real-time

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
    # stdout_api_*.log: 레거시 (NSSM stdout 캡처, service_*.log로 전환됨)
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
    # stdout_worker_*.log: 레거시 (구형 worker-watchdog.ps1, dev/에만 존재)
    # stdout_unified_worker_*.log: 현재 활성 (unified-worker-watchdog.ps1이 stdout 캡처)
    $workerLogs = Get-LogsMultiPattern @("stdout_unified_worker_*.log", "stdout_worker_*.log", "worker_*.log", "unified_worker_*.log")
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
# 1) $LogDir 내 stdout_api_*(레거시, NSSM→service_*.log 전환), api_*
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
# WORKER 뷰는 구조화 본로그(worker_*)를 우선 사용한다.
# stdout_unified_worker_* / stdout_worker_*는 stdout 캡처용 보조 로그라 이벤트 누락이 있을 수 있다.
$workerLogFile = Get-LatestLogFileMultiPattern @("worker_", "unified_worker_")
$frontendLogFile = Get-LatestLogFileMultiPattern @("frontend_2")
$claudeWorkerLogFile = Get-LatestLogFileMultiPattern @("llm_worker_")
# stdout_video_download_worker_: 레거시 (Python 앱 자체 로깅으로 전환됨)
$videoDownloadWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_video_download_worker_", "video_download_worker_")
# stdout_crawl_: 레거시 (Python 앱 자체 로깅으로 전환됨)
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
$startupApiWatchdogLogFile = Get-LatestLogFileMultiPattern @("startup_api_watchdog_")
$startupBrowserWorkersLogFile = Get-LatestLogFileMultiPattern @("startup_browser_workers_")
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

# Plan-runner 표시 이름 추출: "2026-02-25_smart-push-auto-rebase.md" → "smart-push"
# plan_file이 없는 TC runner는 Fallback(runner_id)을 반환
function Get-PlanRunnerDisplayName {
    param([string]$PlanFile, [string]$Fallback = "unknown")
    if (-not $PlanFile) { return $Fallback }
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
# TC runner:  plan-runner-t-{name}-{YYYYMMDD-HHmmss}.log → "t-{name}" (이름에 하이픈 포함 가능)
# 신규 형식:  plan-runner-{8자hex}-{YYYYMMDD-HHmmss}.log → "{8자hex}"
# 구버전:     plan-runner-{YYYYMMDD-HHmmss}.log → "{HHmmss}"
function Get-PlanRunnerFileId {
    param([string]$FileName)
    # TC runner 형식: plan-runner-t-{name...}-YYYYMMDD-HHmmss.log (이름에 하이픈 포함 가능)
    if ($FileName -match 'plan-runner-(t-.+)-\d{8}-\d{6}') { return $Matches[1] }
    # 신규 형식: plan-runner-{8자hex}-YYYYMMDD-HHmmss.log → runner_id 추출
    if ($FileName -match 'plan-runner-([0-9a-f]{8})-\d{8}-\d{6}') { return $Matches[1] }
    # 구버전 형식: plan-runner-YYYYMMDD-HHmmss.log → HHmmss 추출
    if ($FileName -match 'plan-runner-\d{8}-(\d{6})') { return $Matches[1] }
    return "unknown"
}

# plan-runner 로그 파일명에서 타임스탬프 토큰(YYYYMMDD-HHmmss) 추출
function Get-PlanRunnerTimestampToken {
    param([string]$FileName)
    if ($FileName -match 'plan-runner-(?:t-.+|[0-9a-f]{8})-(\d{8}-\d{6})') { return $Matches[1] }
    if ($FileName -match 'plan-runner-(\d{8}-\d{6})') { return $Matches[1] }
    return $null
}

# PR 로그 파일명/runner_id 기준으로 동일 실행의 stream 로그를 찾는다.
# 🔴 전역 최신 stream 폴백은 금지 (다른 runner 로그 오매핑 방지)
function Find-MatchingPlanRunnerStreamLog {
    param(
        [string]$LogDir,
        [string]$PlanLogFileName,
        [string]$RunnerId = ""
    )
    if (-not $LogDir -or -not (Test-Path $LogDir) -or -not $PlanLogFileName) { return $null }

    if ($RunnerId) {
        $byRunner = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${RunnerId}*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($byRunner) { return $byRunner.FullName }
    }

    $fileId = Get-PlanRunnerFileId -FileName $PlanLogFileName
    if ($fileId -and $fileId -ne "unknown") {
        $byFileId = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${fileId}*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($byFileId) { return $byFileId.FullName }
    }

    $tsToken = Get-PlanRunnerTimestampToken -FileName $PlanLogFileName
    if ($tsToken) {
        $byTimestamp = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${tsToken}*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($byTimestamp) { return $byTimestamp.FullName }
    }

    return $null
}

$script:PlanRunnerStreamMissWarningKeys = @{}

function Write-PlanRunnerStreamMissWarning {
    param(
        [string]$Key,
        [string]$PlanLogFileName,
        [string]$RunnerId = ""
    )
    if (-not $Key) { $Key = "PS:unknown" }
    if ($script:PlanRunnerStreamMissWarningKeys.ContainsKey($Key)) { return }
    $script:PlanRunnerStreamMissWarningKeys[$Key] = $true

    $runnerHint = if ($RunnerId) { " runner=$RunnerId" } else { "" }
    $fileHint = if ($PlanLogFileName) { " planLog=$PlanLogFileName" } else { "" }
    Write-Host "[$Key] [WARN] matching plan-runner stream log not found.$runnerHint$fileHint" -ForegroundColor Yellow
}

if ($planRunnerLogFile) {
    $planRunnerStreamLogFile = Find-MatchingPlanRunnerStreamLog `
        -LogDir $planRunnerLogDir `
        -PlanLogFileName ([System.IO.Path]::GetFileName($planRunnerLogFile))
    if (-not $planRunnerStreamLogFile) {
        $prFileId = Get-PlanRunnerFileId -FileName ([System.IO.Path]::GetFileName($planRunnerLogFile))
        Write-PlanRunnerStreamMissWarning -Key "PS:$prFileId" -PlanLogFileName ([System.IO.Path]::GetFileName($planRunnerLogFile))
    }
}

# Redis에서 활성 plan-runner 목록 조회
function Get-ActivePlanRunners {
    param([string]$LogDir)
    $result = @()

    $py = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { return $result }

    # 임시 파일로 Python 코드 전달 (PowerShell -c 인자 전달 시 따옴표 제거 방지)
    $tmpPy = Join-Path $env:TEMP ("logs_planrunner_{0}.py" -f [guid]::NewGuid().ToString("N").Substring(0,8))
    @'
import json, sys
try:
    import redis
    r = redis.Redis(socket_timeout=2)
    r.ping()
    runners = []
    for rid_b in r.smembers("plan-runner:active_runners"):
        rid = rid_b.decode()
        def g(k, _r=r): v = _r.get(k); return v.decode() if v else None
        runners.append({"rid": rid,
            "logPath":    g("plan-runner:runners:" + rid + ":log_file_path"),
            "streamPath": g("plan-runner:runners:" + rid + ":stream_log_path"),
            "planFile":   g("plan-runner:runners:" + rid + ":plan_file"),
            "pid":        g("plan-runner:runners:" + rid + ":pid")})
    print(json.dumps(runners))
except Exception:
    print("[]")
'@ | Set-Content -Path $tmpPy -Encoding UTF8

    $jsonOut = & $py $tmpPy 2>$null
    Remove-Item $tmpPy -ErrorAction SilentlyContinue
    if (-not $jsonOut) { return $result }

    $runners = $jsonOut | ConvertFrom-Json
    foreach ($r in $runners) {
        $displayName = Get-PlanRunnerDisplayName -PlanFile ([System.IO.Path]::GetFileName($r.planFile)) -Fallback $r.rid
        $shortId = $r.rid.Substring(0, [Math]::Min(4, $r.rid.Length))
        $result += @{
            RunnerId    = $r.rid
            ShortId     = $shortId
            DisplayName = $displayName
            LogPath     = $r.logPath
            StreamPath  = $r.streamPath
            PlanFile    = $r.planFile
            PID         = $r.pid
        }
    }
    return $result
}

# Redis 연결 여부 — redis-cli 대신 Python redis 클라이언트 사용 (redis-cli PATH 의존 제거)
$useRedis = $false
$_py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $_py) {
    $pingOut = & $_py -c "import redis; r=redis.Redis(socket_timeout=2); print(r.ping())" 2>$null
    if ($pingOut -and $pingOut.Trim() -eq "True") { $useRedis = $true }
}

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
    @{ Name = "API-Watchdog"; Var = "apiWatchdogLogFile" },
    @{ Name = "Startup-API-WD"; Var = "startupApiWatchdogLogFile" },
    @{ Name = "Startup-Workers"; Var = "startupBrowserWorkersLogFile" }
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
    $startupApiWatchdogLogFile = $null
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
        $runnerHint = if ($prFileId -match '^[0-9a-f]{8}$') { $prFileId } else { "" }
        $streamPath = Find-MatchingPlanRunnerStreamLog `
            -LogDir $planRunnerLogDir `
            -PlanLogFileName $lf.Name `
            -RunnerId $runnerHint
        if ($streamPath) {
            Show-LogContent -FilePath $streamPath -Label "PS:$prFileId" -Color DarkGray -TailLines ([Math]::Min($TailLines, 20))
        } else {
            Write-PlanRunnerStreamMissWarning `
                -Key "PS:$prFileId" `
                -PlanLogFileName $lf.Name `
                -RunnerId $runnerHint
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

# Main logic
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Log Viewer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Real-time follow mode — Python log_viewer에 위임 (2026-03-31)
if ($Follow) {
    $pyExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $pyArgs = @("-m", "app.log_viewer")

    if ($Target -ne "all") {
        $pyArgs += $Target.ToLower()
    }

    $pyArgs += "--follow"

    if ($Admin) {
        $pyArgs += "--admin"
    }

    if ($Cleanup) {
        $pyArgs += "--cleanup"
    }

    Push-Location $ProjectRoot
    try {
        & $pyExe @pyArgs
    } finally {
        Pop-Location
    }
    exit $LASTEXITCODE
} else {
    # Static log display — Python log_viewer에 위임
    $pyExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $pyArgs = @("-m", "app.log_viewer")

    # "all" → target 생략 (Python cli에서 None = 전체 소스 표시)
    if ($Target -ne "all") {
        $pyArgs += $Target.ToLower()
    }

    $pyArgs += "--lines"
    $pyArgs += "$Lines"

    if ($Admin) {
        $pyArgs += "--admin"
    }

    if ($Cleanup) {
        $pyArgs += "--cleanup"
    }

    Push-Location $ProjectRoot
    try {
        & $pyExe @pyArgs
    } finally {
        Pop-Location
    }
}

Write-Host ""
