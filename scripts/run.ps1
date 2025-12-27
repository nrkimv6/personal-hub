# Monitor Page - Integrated Run Script
# Starts all processes, shows logs, and stops on exit (Ctrl+C)
#
# Production mode (default): API + Frontend only, workers disabled
# Development mode (-Dev): All features enabled including workers

param(
    [switch]$Dev,        # Dev mode: use different ports (API: 8001, Frontend: 5174) + workers
    [switch]$SkipWorker  # Skip worker even in Dev mode (for PyCharm debugger)
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Mode and port settings
if ($Dev) {
    $ApiPort = 8001
    $FrontendPort = 5174
    $AppMode = "development"
    $RunWorkers = -not $SkipWorker  # Run workers unless explicitly skipped
} else {
    $ApiPort = 8000
    $FrontendPort = 5173
    $AppMode = "production"
    $RunWorkers = $false  # Production mode: no workers
}

# Set APP_MODE environment variable for backend
$env:APP_MODE = $AppMode

# Set Playwright browsers path to project-local directory
# This allows consistent browser path across all execution modes
$PlaywrightBrowsersPath = Join-Path $ProjectRoot ".playwright"
$env:PLAYWRIGHT_BROWSERS_PATH = $PlaywrightBrowsersPath

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page - Integrated Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Show mode info
if ($Dev) {
    Write-Host "[MODE] Development - All features enabled" -ForegroundColor Green
    Write-Host "       API: $ApiPort, Frontend: $FrontendPort, Workers: $(if ($RunWorkers) { 'ON' } else { 'OFF' })" -ForegroundColor Green
} else {
    Write-Host "[MODE] Production - View only (workers disabled)" -ForegroundColor Yellow
    Write-Host "       API: $ApiPort, Frontend: $FrontendPort, Workers: OFF" -ForegroundColor Yellow
}
Write-Host ""

# Clean up ports before starting (kill any zombie processes from previous runs)
Write-Host "[*] Cleaning up ports..." -ForegroundColor Yellow
$portsToClean = @($ApiPort, $FrontendPort)
foreach ($port in $portsToClean) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "    [!] Killing zombie process on port ${port}: $($proc.ProcessName) (PID: $procId)" -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 300
            }
        }
    }
}

# Clean up browser profiles before starting (Dev mode only)
# Production mode doesn't use browsers - don't touch anything
if ($Dev) {
    $browserProfilesPath = Join-Path $ProjectRoot "data\browser_profiles"

    Write-Host "[*] Cleaning up Playwright browsers..." -ForegroundColor Yellow

    # Kill orphaned Playwright chromium processes (not regular Chrome)
    $chromeProcs = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
    $killedCount = 0
    foreach ($proc in $chromeProcs) {
        try {
            $procPath = $proc.Path
            if ($procPath -and $procPath -like "*ms-playwright*") {
                Write-Host "    [!] Killing orphaned Playwright browser (PID: $($proc.Id))" -ForegroundColor Yellow
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $killedCount++
            }
        } catch {
            # Ignore access denied errors for system processes
        }
    }
    if ($killedCount -gt 0) {
        Write-Host "    [+] Killed $killedCount Playwright browser process(es)" -ForegroundColor Green
        Start-Sleep -Milliseconds 500
    }

    # Clean up LOCK files
    if (Test-Path $browserProfilesPath) {
        $lockFiles = Get-ChildItem -Path $browserProfilesPath -Filter "LOCK" -Recurse -ErrorAction SilentlyContinue
        if ($lockFiles) {
            $cleanedCount = 0
            foreach ($lockFile in $lockFiles) {
                try {
                    Remove-Item $lockFile.FullName -Force -ErrorAction Stop
                    $cleanedCount++
                } catch {
                    # File may be in use
                }
            }
            if ($cleanedCount -gt 0) {
                Write-Host "    [+] Cleaned up $cleanedCount LOCK file(s)" -ForegroundColor Green
            }
        }

        # Clean Crashpad data (can cause issues)
        $crashpadDirs = Get-ChildItem -Path $browserProfilesPath -Directory -Filter "Crashpad" -Recurse -ErrorAction SilentlyContinue
        foreach ($crashpad in $crashpadDirs) {
            Remove-Item -Path "$($crashpad.FullName)\*" -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($crashpadDirs) {
            Write-Host "    [+] Cleaned up Crashpad data" -ForegroundColor Green
        }
    }

    Write-Host ""
}

Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Start all processes (API, Worker, Frontend)"
Write-Host "  2. Show real-time logs"
Write-Host "  3. Stop all processes when you press Ctrl+C"
Write-Host ""

# Register cleanup on script exit
$stopScript = Join-Path $ScriptDir "stop.ps1"

# Use Register-EngineEvent for Ctrl+C handling
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-Host "`n`n[!] Shutting down..." -ForegroundColor Yellow
}

try {
    # Step 1: Start processes
    Write-Host "[Step 1] Starting processes..." -ForegroundColor Cyan
    Write-Host "----------------------------------------"

    $startScript = Join-Path $ScriptDir "start.ps1"

    if ($Dev) {
        # In Dev mode: API/Worker background + Frontend foreground + show all logs
        Write-Host "[!] Dev mode: Frontend in foreground + backend logs" -ForegroundColor Yellow
        Write-Host ""

        # Start API and Worker only (not frontend) with Dev flag
        $env:SKIP_FRONTEND = "true"
        if (-not $RunWorkers) {
            $env:SKIP_WORKER = "true"
            $env:SKIP_CRAWL_WORKER = "true"
            $env:SKIP_CLAUDE_WORKER = "true"
        }
        & $startScript -Dev
        $env:SKIP_FRONTEND = $null
        $env:SKIP_WORKER = $null
        $env:SKIP_CRAWL_WORKER = $null
        $env:SKIP_CLAUDE_WORKER = $null

        # Wait for log files to be created (watchdog starts worker after a delay)
        Start-Sleep -Seconds 4

        # Find the most recent log files by filename (contains timestamp like worker_20251211_094846.log)
        # Using Name sort instead of LastWriteTime because old log files may be updated when processes stop
        $LogDir = Join-Path $ProjectRoot "logs\dev"

        $apiLog = Get-ChildItem -Path $LogDir -Filter "stdout_api_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1

        # Worker log may be created by watchdog with delay, so we track the latest one dynamically
        $workerLog = Get-ChildItem -Path $LogDir -Filter "stdout_worker_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        $workerLogName = if ($workerLog) { $workerLog.Name } else { $null }

        # Crawl worker log (Instagram + Universal)
        $crawlWorkerLog = Get-ChildItem -Path $LogDir -Filter "stdout_crawl_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        $crawlWorkerLogName = if ($crawlWorkerLog) { $crawlWorkerLog.Name } else { $null }

        # Claude worker log (LLM worker)
        $claudeWorkerLog = Get-ChildItem -Path $LogDir -Filter "stdout_llm_worker_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        $claudeWorkerLogName = if ($claudeWorkerLog) { $claudeWorkerLog.Name } else { $null }

        Write-Host ""
        Write-Host "[Step 2] Starting frontend + tailing backend logs..." -ForegroundColor Cyan
        Write-Host "----------------------------------------"

        # Show existing log content first
        if ($apiLog) {
            Write-Host "[API] === Log from start ===" -ForegroundColor Cyan
            Get-Content $apiLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[API] $_" -ForegroundColor Cyan
            }
        }
        if ($workerLog) {
            Write-Host "[WORKER] === Log from start ===" -ForegroundColor Magenta
            Get-Content $workerLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[WORKER] $_" -ForegroundColor Magenta
            }
        }
        if ($crawlWorkerLog) {
            Write-Host "[CRAWL] === Log from start ===" -ForegroundColor DarkCyan
            Get-Content $crawlWorkerLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[CRAWL] $_" -ForegroundColor DarkCyan
            }
        }
        if ($claudeWorkerLog) {
            Write-Host "[CLAUDE] === Log from start ===" -ForegroundColor Blue
            Get-Content $claudeWorkerLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[CLAUDE] $_" -ForegroundColor Blue
            }
        }

        Write-Host ""
        Write-Host "--- Frontend starting (Ctrl+C to stop all) ---" -ForegroundColor Yellow
        Write-Host ""

        # Track log file positions for tailing
        $apiPos = if ($apiLog) { (Get-Item $apiLog.FullName).Length } else { 0 }
        $workerPos = if ($workerLog) { (Get-Item $workerLog.FullName).Length } else { 0 }
        $crawlWorkerPos = if ($crawlWorkerLog) { (Get-Item $crawlWorkerLog.FullName).Length } else { 0 }
        $claudeWorkerPos = if ($claudeWorkerLog) { (Get-Item $claudeWorkerLog.FullName).Length } else { 0 }

        # Watchdog logs (if exists)
        $watchdogLogFile = Join-Path $LogDir "watchdog.log"
        $watchdogPos = if (Test-Path $watchdogLogFile) { (Get-Item $watchdogLogFile).Length } else { 0 }
        $crawlWatchdogLogFile = Join-Path $LogDir "crawl_watchdog.log"
        $crawlWatchdogPos = if (Test-Path $crawlWatchdogLogFile) { (Get-Item $crawlWatchdogLogFile).Length } else { 0 }
        $claudeWatchdogLogFile = Join-Path $LogDir "claude_watchdog.log"
        $claudeWatchdogPos = if (Test-Path $claudeWatchdogLogFile) { (Get-Item $claudeWatchdogLogFile).Length } else { 0 }

        # Start frontend in background (so we can tail logs)
        $FrontendDir = Join-Path $ProjectRoot "frontend"
        $frontendLogFile = Join-Path $LogDir "frontend_dev.log"

        # Start frontend and capture its actual PID via port
        $FrontendPidFile = Join-Path $ProjectRoot ".pids\frontend_dev.pid"
        "DEV_MODE" | Out-File $FrontendPidFile -Encoding ascii
        $frontendPos = 0

        # Start frontend in background with VITE_API_PORT for proxy
        Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "cd /d `"$FrontendDir`" && set VITE_API_PORT=$ApiPort && npm run dev -- --host --port $FrontendPort > `"$frontendLogFile`" 2>&1" `
            -WindowStyle Hidden

        # Wait for vite to start (check port with timeout)
        Write-Host "[*] Waiting for frontend to start on port $FrontendPort..." -ForegroundColor Gray
        $maxWait = 30  # 30 seconds max
        $waited = 0
        while ($waited -lt $maxWait) {
            $conn = Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue
            if ($conn) {
                Write-Host "[+] Frontend is running on port $FrontendPort" -ForegroundColor Green
                break
            }
            Start-Sleep -Seconds 1
            $waited++

            # Also tail logs while waiting
            if (Test-Path $frontendLogFile) {
                $currentSize = (Get-Item $frontendLogFile).Length
                if ($currentSize -gt $frontendPos) {
                    $stream = [System.IO.FileStream]::new($frontendLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    $stream.Seek($frontendPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                    while ($null -ne ($line = $reader.ReadLine())) {
                        Write-Host "[FRONTEND] $line" -ForegroundColor Green
                    }
                    $frontendPos = $stream.Position
                    $reader.Close()
                    $stream.Close()
                }
            }
        }

        if ($waited -ge $maxWait) {
            Write-Host "[!] Frontend failed to start within ${maxWait}s" -ForegroundColor Red
            throw "Frontend startup timeout"
        }

        try {
            # Tail all logs while frontend runs (check port)
            while ($true) {
                # Check if frontend is still running via port
                $conn = Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue
                if (-not $conn) {
                    Write-Host "[!] Frontend stopped" -ForegroundColor Yellow
                    break
                }
                # Tail API log
                if ($apiLog -and (Test-Path $apiLog.FullName)) {
                    $currentSize = (Get-Item $apiLog.FullName).Length
                    if ($currentSize -gt $apiPos) {
                        $stream = [System.IO.FileStream]::new($apiLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($apiPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[API] $line" -ForegroundColor Cyan
                        }
                        $apiPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Watchdog log
                if (Test-Path $watchdogLogFile) {
                    $currentSize = (Get-Item $watchdogLogFile).Length
                    if ($currentSize -gt $watchdogPos) {
                        $stream = [System.IO.FileStream]::new($watchdogLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($watchdogPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[WATCHDOG] $line" -ForegroundColor DarkYellow
                        }
                        $watchdogPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Worker log (check for new log file from watchdog restart)
                $latestWorkerLog = Get-ChildItem -Path $LogDir -Filter "stdout_worker_*.log" -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending | Select-Object -First 1
                if ($latestWorkerLog -and $latestWorkerLog.Name -ne $workerLogName) {
                    # New worker log file detected (worker restarted by watchdog)
                    Write-Host "[WORKER] === New worker log: $($latestWorkerLog.Name) ===" -ForegroundColor Yellow
                    $workerLog = $latestWorkerLog
                    $workerLogName = $latestWorkerLog.Name
                    $workerPos = 0
                }
                if ($workerLog -and (Test-Path $workerLog.FullName)) {
                    $currentSize = (Get-Item $workerLog.FullName).Length
                    if ($currentSize -gt $workerPos) {
                        $stream = [System.IO.FileStream]::new($workerLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($workerPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[WORKER] $line" -ForegroundColor Magenta
                        }
                        $workerPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Crawl Watchdog log
                if (Test-Path $crawlWatchdogLogFile) {
                    $currentSize = (Get-Item $crawlWatchdogLogFile).Length
                    if ($currentSize -gt $crawlWatchdogPos) {
                        $stream = [System.IO.FileStream]::new($crawlWatchdogLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($crawlWatchdogPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[CRAWL-WATCHDOG] $line" -ForegroundColor DarkYellow
                        }
                        $crawlWatchdogPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Crawl Worker log (check for new log file from watchdog restart)
                $latestCrawlWorkerLog = Get-ChildItem -Path $LogDir -Filter "stdout_crawl_*.log" -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending | Select-Object -First 1
                if ($latestCrawlWorkerLog -and $latestCrawlWorkerLog.Name -ne $crawlWorkerLogName) {
                    Write-Host "[CRAWL] === New worker log: $($latestCrawlWorkerLog.Name) ===" -ForegroundColor Yellow
                    $crawlWorkerLog = $latestCrawlWorkerLog
                    $crawlWorkerLogName = $latestCrawlWorkerLog.Name
                    $crawlWorkerPos = 0
                }
                if ($crawlWorkerLog -and (Test-Path $crawlWorkerLog.FullName)) {
                    $currentSize = (Get-Item $crawlWorkerLog.FullName).Length
                    if ($currentSize -gt $crawlWorkerPos) {
                        $stream = [System.IO.FileStream]::new($crawlWorkerLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($crawlWorkerPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[CRAWL] $line" -ForegroundColor DarkCyan
                        }
                        $crawlWorkerPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Claude Watchdog log
                if (Test-Path $claudeWatchdogLogFile) {
                    $currentSize = (Get-Item $claudeWatchdogLogFile).Length
                    if ($currentSize -gt $claudeWatchdogPos) {
                        $stream = [System.IO.FileStream]::new($claudeWatchdogLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($claudeWatchdogPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[CLAUDE-WATCHDOG] $line" -ForegroundColor DarkBlue
                        }
                        $claudeWatchdogPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Claude Worker log (check for new log file from watchdog restart)
                $latestClaudeWorkerLog = Get-ChildItem -Path $LogDir -Filter "stdout_llm_worker_*.log" -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending | Select-Object -First 1
                if ($latestClaudeWorkerLog -and $latestClaudeWorkerLog.Name -ne $claudeWorkerLogName) {
                    Write-Host "[CLAUDE] === New worker log: $($latestClaudeWorkerLog.Name) ===" -ForegroundColor Yellow
                    $claudeWorkerLog = $latestClaudeWorkerLog
                    $claudeWorkerLogName = $latestClaudeWorkerLog.Name
                    $claudeWorkerPos = 0
                }
                if ($claudeWorkerLog -and (Test-Path $claudeWorkerLog.FullName)) {
                    $currentSize = (Get-Item $claudeWorkerLog.FullName).Length
                    if ($currentSize -gt $claudeWorkerPos) {
                        $stream = [System.IO.FileStream]::new($claudeWorkerLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($claudeWorkerPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[CLAUDE] $line" -ForegroundColor Blue
                        }
                        $claudeWorkerPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Frontend log
                if (Test-Path $frontendLogFile) {
                    $currentSize = (Get-Item $frontendLogFile).Length
                    if ($currentSize -gt $frontendPos) {
                        $stream = [System.IO.FileStream]::new($frontendLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($frontendPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[FRONTEND] $line" -ForegroundColor Green
                        }
                        $frontendPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                Start-Sleep -Milliseconds 200
            }
        } finally {
            # Cleanup - kill frontend via port
            $conn = Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue
            if ($conn) {
                $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
                foreach ($pid in $pids) {
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $FrontendPidFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        # Normal (Production) mode: all background, workers disabled
        # Set environment variables to skip all workers
        $env:SKIP_WORKER = "true"
        $env:SKIP_CRAWL_WORKER = "true"
        $env:SKIP_CLAUDE_WORKER = "true"

        & $startScript

        # Clean up environment variables
        $env:SKIP_WORKER = $null
        $env:SKIP_CRAWL_WORKER = $null
        $env:SKIP_CLAUDE_WORKER = $null

        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
            Write-Host "[!] Start script returned non-zero exit code" -ForegroundColor Yellow
        }

        # Step 2: Show logs (in follow mode)
        Write-Host ""
        Write-Host "[Step 2] Following logs (Ctrl+C to stop)..." -ForegroundColor Cyan
        Write-Host "----------------------------------------"

        $logsScript = Join-Path $ScriptDir "logs.ps1"
        & $logsScript -Follow
    }

} finally {
    # Step 3: Stop all processes on exit
    Write-Host ""
    Write-Host ""
    Write-Host "[Step 3] Stopping all processes..." -ForegroundColor Yellow
    Write-Host "----------------------------------------"

    # Kill frontend process directly by port first (more reliable than stop.ps1)
    # This ensures frontend is killed even if stop.ps1 fails or is interrupted
    $conn = Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue
    if ($conn) {
        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            Write-Host "[*] Killing frontend on port $FrontendPort (PID: $procId)" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }

    # Kill API process directly by port
    $conn = Get-NetTCPConnection -LocalPort $ApiPort -ErrorAction SilentlyContinue
    if ($conn) {
        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            Write-Host "[*] Killing API on port $ApiPort (PID: $procId)" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }

    # Stop the rest (workers, watchdogs, etc.) via stop.ps1
    if ($Dev) {
        & $stopScript -Force -Dev
    } else {
        & $stopScript -Force
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Run complete" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
}
