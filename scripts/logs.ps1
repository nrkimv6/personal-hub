# Monitor Page - Log Viewer Script
# View logs for API server, worker, and frontend in real-time

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "api", "worker", "frontend", "list")]
    [string]$Target = "all",

    [Parameter()]
    [int]$Lines = 50,

    [Parameter()]
    [switch]$Follow,

    [Parameter()]
    [switch]$FromStart,  # Show logs from beginning of file (not just tail)

    [Parameter()]
    [switch]$Dev,  # Use development log directory (logs/dev/)

    [Parameter()]
    [switch]$Help
)

# Set console output encoding to UTF-8 for Korean support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Log directory based on mode
if ($Dev) {
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    # Create dev log directory if it doesn't exist
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

# Get latest log file function (by filename timestamp, not LastWriteTime)
function Get-LatestLogFile {
    param([string]$Prefix)

    $pattern = Join-Path $LogDir "$Prefix*.log"
    # Sort by Name descending - filenames contain timestamps like api_20251211_094846.log
    $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    if ($files) {
        return $files[0].FullName
    }
    return $null
}

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
        if ($Dev) {
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
    $apiLogs = Get-LogsMultiPattern @("stdout_api_*.log", "api_*.log", "service_MonitorPage-Dev.log", "service_MonitorPage.log")
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

    # Auto-next logs (별도 디렉토리)
    Write-Host "[Auto-Next Logs] ($autoNextLogDir)" -ForegroundColor Yellow
    if (Test-Path $autoNextLogDir) {
        $anLogs = Get-ChildItem -Path $autoNextLogDir -Filter "auto-next-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
        if ($anLogs) {
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

# Get log files - try both patterns (stdout_* for NSSM, plain for direct run)
function Get-LatestLogFileMultiPattern {
    param([string[]]$Prefixes)

    foreach ($prefix in $Prefixes) {
        $file = Get-LatestLogFile $prefix
        if ($file) { return $file }
    }
    return $null
}

# API 로그: 모든 후보에서 LastWriteTime이 가장 최신인 파일 선택
# Python 마이그레이션 후 API 앱은 LOG_DIR="logs" (하드코딩)에 api_*.log를 기록.
# Dev 모드: $LogDir=logs/dev/ (stdout_api_*, NSSM log) + logs/ (api_*)
# 운영 모드: $LogDir=logs/ (stdout_api_*, api_*, NSSM log) 모두 동일 디렉토리
$apiCandidates = @()
# 1) $LogDir 내 stdout_api_*, api_*
foreach ($prefix in @("stdout_api_*.log", "api_*.log")) {
    $found = Get-ChildItem (Join-Path $LogDir $prefix) -ErrorAction SilentlyContinue
    if ($found) { $apiCandidates += $found }
}
# 2) Dev 모드: base logs/ 디렉토리의 api_* (앱의 LOG_DIR가 logs/ 고정)
if ($Dev) {
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
$igWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_instagram_", "instagram_")
$claudeWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_llm_worker_", "llm_worker_")
$videoDownloadWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_video_download_worker_", "video_download_worker_")
$crawlWorkerLogFile = Get-LatestLogFileMultiPattern @("stdout_crawl_", "crawl_worker_")

# Static log files (not timestamped)
$serviceRunnerLogFile = Join-Path $LogDir "service_runner.log"
$watchdogLogFile = Join-Path $LogDir "watchdog.log"
$igWatchdogLogFile = Join-Path $LogDir "instagram_watchdog.log"
$claudeWatchdogLogFile = Join-Path $LogDir "claude_watchdog.log"
$videoDownloadWatchdogLogFile = Join-Path $LogDir "video_download_watchdog.log"
$crawlWatchdogLogFile = Join-Path $LogDir "crawl_watchdog.log"
$cloudflaredLogFile = Join-Path (Join-Path $ProjectRoot "logs") "cloudflared.log"

# Auto-next 로그: wtools/common/logs/ 에서 최신 파일
$autoNextLogDir = "D:\work\project\service\wtools\common\logs"
$autoNextLogFile = $null
if (Test-Path $autoNextLogDir) {
    $found = Get-ChildItem -Path $autoNextLogDir -Filter "auto-next-*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch "stream" } |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($found) { $autoNextLogFile = $found.FullName }
}
$autoNextStreamLogFile = $null
if (Test-Path $autoNextLogDir) {
    $found = Get-ChildItem -Path $autoNextLogDir -Filter "auto-next-stream-*.log" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($found) { $autoNextStreamLogFile = $found.FullName }
}

# Check if log files are stale (created more than 1 hour before the latest API log)
function Test-StaleLogFile {
    param([string]$FilePath, [string]$ReferenceFile)

    if (-not $FilePath -or -not $ReferenceFile) { return $false }
    if (-not (Test-Path $FilePath) -or -not (Test-Path $ReferenceFile)) { return $false }

    $fileTime = (Get-Item $FilePath).LastWriteTime
    $refTime = (Get-Item $ReferenceFile).LastWriteTime

    # If the file was last modified more than 1 hour before the reference file, it's stale
    return ($refTime - $fileTime).TotalHours -gt 1
}

# Warn about potentially stale log files and exclude them
if ($apiLogFile) {
    # Timestamped log files (worker, frontend, ig-worker, claude)
    $timestampedLogs = @(
        @{ Name = "Worker"; Var = "workerLogFile" },
        @{ Name = "IG-Worker"; Var = "igWorkerLogFile" },
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

    # Static log files (watchdog, service_runner) - check LastWriteTime directly
    $staticLogs = @(
        @{ Name = "Watchdog"; Var = "watchdogLogFile" },
        @{ Name = "IG-Watchdog"; Var = "igWatchdogLogFile" },
        @{ Name = "Claude-Watchdog"; Var = "claudeWatchdogLogFile" },
        @{ Name = "Video-DL-Watchdog"; Var = "videoDownloadWatchdogLogFile" },
        @{ Name = "Crawl-Watchdog"; Var = "crawlWatchdogLogFile" },
        @{ Name = "Service Runner"; Var = "serviceRunnerLogFile" }
    )

    foreach ($log in $staticLogs) {
        $logFile = Get-Variable -Name $log.Var -ValueOnly -ErrorAction SilentlyContinue
        if ($logFile -and (Test-StaleLogFile $logFile $apiLogFile)) {
            Write-Host "[!] $($log.Name) log may be stale (from previous session)" -ForegroundColor Yellow
            Set-Variable -Name $log.Var -Value $null
        }
    }
}

# Show log content function
function Show-LogContent {
    param(
        [string]$FilePath,
        [string]$Label,
        [ConsoleColor]$Color,
        [int]$TailLines
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[$Label] Log file not found" -ForegroundColor Gray
        return
    }

    Write-Host "`n========================================" -ForegroundColor $Color
    Write-Host "  $Label Log" -ForegroundColor $Color
    Write-Host "  File: $(Split-Path $FilePath -Leaf)" -ForegroundColor $Color
    Write-Host "========================================" -ForegroundColor $Color
    Write-Host ""

    # Read last N lines
    $content = Get-Content $FilePath -Tail $TailLines -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($content) {
        foreach ($line in $content) {
            # Color based on log level
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
        [string]$IgWorkerLog,
        [string]$ClaudeWorkerLog,
        [string]$VideoDownloadLog,
        [string]$CrawlWorkerLog,
        [string]$ServiceRunnerLog,
        [string]$WatchdogLog,
        [string]$IgWatchdogLog,
        [string]$ClaudeWatchdogLog,
        [string]$VideoDownloadWatchdogLog,
        [string]$CrawlWatchdogLog,
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
        "IG-WORKER"   = @{ Path = $IgWorkerLog;       Color = "DarkMagenta"; Tail = 3 }
        "CLAUDE"      = @{ Path = $ClaudeWorkerLog;   Color = "Blue";        Tail = 3 }
        "VIDEO-DL"    = @{ Path = $VideoDownloadLog;  Color = "DarkGreen";   Tail = 5 }
        "CRAWL"       = @{ Path = $CrawlWorkerLog;    Color = "DarkBlue";    Tail = 5 }
        "FRONTEND"    = @{ Path = $FrontendLog;       Color = "Green";       Tail = 3 }
        "WATCHDOG"    = @{ Path = $WatchdogLog;       Color = "DarkYellow";  Tail = 2 }
        "IG-WD"       = @{ Path = $IgWatchdogLog;     Color = "DarkYellow";  Tail = 2 }
        "CLAUDE-WD"   = @{ Path = $ClaudeWatchdogLog; Color = "DarkYellow";  Tail = 2 }
        "VIDEO-DL-WD" = @{ Path = $VideoDownloadWatchdogLog; Color = "DarkYellow"; Tail = 2 }
        "CRAWL-WD"    = @{ Path = $CrawlWatchdogLog;  Color = "DarkYellow";  Tail = 2 }
        "AUTO-NEXT"   = @{ Path = $autoNextLogFile;    Color = "White";       Tail = 10 }
        "AN-STREAM"   = @{ Path = $autoNextStreamLogFile; Color = "DarkGray"; Tail = 5 }
    }

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
            $filePositions[$source] = (Get-Item $filePath).Length

            # Show last N lines initially
            $initLines = Get-Content $filePath -Tail $config.Tail -Encoding UTF8 -ErrorAction SilentlyContinue
            foreach ($line in $initLines) {
                Write-Host "[$source] $line" -ForegroundColor $config.Color
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
        "IG-WORKER"   = @("stdout_instagram_*.log", "instagram_*.log")
        "CLAUDE"      = @("stdout_llm_worker_*.log", "llm_worker_*.log")
        "VIDEO-DL"    = @("stdout_video_download_worker_*.log", "video_download_worker_*.log")
        "CRAWL"       = @("stdout_crawl_*.log", "crawl_worker_*.log")
        "FRONTEND"    = @("frontend_2*.log")
    }

    # Helper to find latest log from multiple patterns
    # Dev 모드일 때 base logs/ 디렉토리도 탐색 (API 앱의 LOG_DIR가 logs/ 고정)
    function Get-LatestLogFromPatterns {
        param([string[]]$Patterns)
        $searchDirs = @($LogDir)
        if ($Dev) {
            $baseLogDir = Join-Path $ProjectRoot "logs"
            if ($baseLogDir -ne $LogDir) { $searchDirs += $baseLogDir }
        }
        $latestLog = $null
        foreach ($dir in $searchDirs) {
            foreach ($pattern in $Patterns) {
                $found = Get-ChildItem -Path $dir -Filter $pattern -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending | Select-Object -First 1
                if ($found -and (-not $latestLog -or $found.Name -gt $latestLog.Name)) {
                    $latestLog = $found
                }
            }
        }
        return $latestLog
    }

    # Auto-next 로그 전용 패턴 (별도 디렉토리)
    $autoNextLogPatterns = @{
        "AUTO-NEXT" = @{ Dir = $autoNextLogDir; Filter = "auto-next-*.log"; Exclude = "stream" }
        "AN-STREAM" = @{ Dir = $autoNextLogDir; Filter = "auto-next-stream-*.log"; Exclude = $null }
    }

    try {
        while ($true) {
            # Auto-next 로그 자동 감지 (별도 디렉토리)
            foreach ($source in $autoNextLogPatterns.Keys) {
                $cfg = $autoNextLogPatterns[$source]
                if (-not (Test-Path $cfg.Dir)) { continue }
                $candidates = Get-ChildItem -Path $cfg.Dir -Filter $cfg.Filter -ErrorAction SilentlyContinue
                if ($cfg.Exclude) { $candidates = $candidates | Where-Object { $_.Name -notmatch $cfg.Exclude } }
                $latest = $candidates | Sort-Object Name -Descending | Select-Object -First 1
                if ($latest) {
                    $currentName = $logFileNames[$source]
                    if ($latest.Name -ne $currentName) {
                        Write-Host "[$source] === Switched to new log: $($latest.Name) ===" -ForegroundColor Yellow
                        $logFiles[$source] = $latest.FullName
                        $logFileNames[$source] = $latest.Name
                        $logColors[$source] = $logConfig[$source].Color
                        $filePositions[$source] = 0
                    }
                }
            }

            # Check for new log files (service restart detection)
            foreach ($source in $timestampedLogPatterns.Keys) {
                $patterns = $timestampedLogPatterns[$source]
                $latestLog = Get-LatestLogFromPatterns $patterns

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

            foreach ($source in $logFiles.Keys) {
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
            Start-LogTail -FilePath $workerLogFile -Prefix "Worker"
        }
        "frontend" {
            Start-LogTail -FilePath $frontendLogFile -Prefix "Frontend"
        }
        default {
            Start-CombinedLogTail `
                -ApiLog $apiLogFile `
                -WorkerLog $workerLogFile `
                -FrontendLog $frontendLogFile `
                -IgWorkerLog $igWorkerLogFile `
                -ClaudeWorkerLog $claudeWorkerLogFile `
                -VideoDownloadLog $videoDownloadWorkerLogFile `
                -CrawlWorkerLog $crawlWorkerLogFile `
                -ServiceRunnerLog $serviceRunnerLogFile `
                -WatchdogLog $watchdogLogFile `
                -IgWatchdogLog $igWatchdogLogFile `
                -ClaudeWatchdogLog $claudeWatchdogLogFile `
                -VideoDownloadWatchdogLog $videoDownloadWatchdogLogFile `
                -CrawlWatchdogLog $crawlWatchdogLogFile `
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
            Show-LogContent -FilePath $workerLogFile -Label "Worker" -Color Magenta -TailLines $Lines
        }
        "frontend" {
            Show-LogContent -FilePath $frontendLogFile -Label "Frontend" -Color Green -TailLines $Lines
        }
        default {
            Show-LogContent -FilePath $apiLogFile -Label "API Server" -Color Cyan -TailLines $Lines
            Show-LogContent -FilePath $workerLogFile -Label "Worker" -Color Magenta -TailLines $Lines
            Show-LogContent -FilePath $frontendLogFile -Label "Frontend" -Color Green -TailLines $Lines
        }
    }
}

Write-Host ""
