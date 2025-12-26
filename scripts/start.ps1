# Monitor Page - Background Process Startup Script
# Starts FastAPI server, monitoring worker, and Frontend in background

param(
    [switch]$Dev  # Dev mode: use different ports (8001, 5174) for development
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $ProjectRoot "frontend"

# Port and mode settings - Dev mode uses different ports to avoid affecting production
if ($Dev) {
    $ApiPort = 8001
    $FrontendPort = 5174
    $AppMode = "development"
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    Write-Host "[DEV MODE] Using development ports (API: $ApiPort, Frontend: $FrontendPort)" -ForegroundColor Yellow
} else {
    $ApiPort = 8000
    $FrontendPort = 5173
    $AppMode = "production"
    $LogDir = Join-Path $ProjectRoot "logs"
}

# Set APP_MODE environment variable (will be inherited by child processes)
$env:APP_MODE = $AppMode

# Create log directory
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# PID file paths
$PidDir = Join-Path $ProjectRoot ".pids"
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# PID files - Dev mode uses separate files to allow both environments to run
$PidSuffix = if ($Dev) { "_dev" } else { "" }
$ApiPidFile = Join-Path $PidDir "api$PidSuffix.pid"
$WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
$ClaudeWorkerPidFile = Join-Path $PidDir "claude_worker$PidSuffix.pid"
$FrontendPidFile = Join-Path $PidDir "frontend$PidSuffix.pid"

# Check if process is running
function Test-ProcessRunning {
    param([string]$PidFile)

    if (Test-Path $PidFile) {
        $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($process) {
                return $true
            }
        }
    }
    return $false
}

# Kill process using specific port
function Stop-ProcessOnPort {
    param([int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "    [!] Killing process on port ${Port}: $($proc.Name) (PID: $procId)" -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
            }
        }
        return $true
    }
    return $false
}

# Check API server
if (Test-ProcessRunning $ApiPidFile) {
    $apiPid = Get-Content $ApiPidFile
    Write-Host "[!] API server already running (PID: $apiPid)" -ForegroundColor Yellow
    $runApi = $false
} else {
    $runApi = $true
}

# Check Worker
if ($env:SKIP_WORKER -eq "true") {
    Write-Host "[!] Skipping worker (SKIP_WORKER=true)" -ForegroundColor Yellow
    $runWorker = $false
} elseif (Test-ProcessRunning $WorkerPidFile) {
    $workerPid = Get-Content $WorkerPidFile
    Write-Host "[!] Worker already running (PID: $workerPid)" -ForegroundColor Yellow
    $runWorker = $false
} else {
    $runWorker = $true
}

# Check Crawl Worker (via Watchdog)
$CrawlWatchdogPidFile = Join-Path $PidDir "crawl_watchdog$PidSuffix.pid"
if ($env:SKIP_CRAWL_WORKER -eq "true") {
    Write-Host "[!] Skipping Crawl worker (SKIP_CRAWL_WORKER=true)" -ForegroundColor Yellow
    $runCrawlWorker = $false
} elseif (Test-ProcessRunning $CrawlWatchdogPidFile) {
    $crawlWatchdogPid = Get-Content $CrawlWatchdogPidFile
    Write-Host "[!] Crawl Watchdog already running (PID: $crawlWatchdogPid)" -ForegroundColor Yellow
    $runCrawlWorker = $false
} else {
    $runCrawlWorker = $true
}

# Check Claude Worker (via Watchdog)
$ClaudeWatchdogPidFile = Join-Path $PidDir "claude_watchdog$PidSuffix.pid"
if ($env:SKIP_CLAUDE_WORKER -eq "true") {
    Write-Host "[!] Skipping Claude worker (SKIP_CLAUDE_WORKER=true)" -ForegroundColor Yellow
    $runClaudeWorker = $false
} elseif (Test-ProcessRunning $ClaudeWatchdogPidFile) {
    $claudeWatchdogPid = Get-Content $ClaudeWatchdogPidFile
    Write-Host "[!] Claude Watchdog already running (PID: $claudeWatchdogPid)" -ForegroundColor Yellow
    $runClaudeWorker = $false
} else {
    $runClaudeWorker = $true
}

# Check Frontend
if ($env:SKIP_FRONTEND -eq "true") {
    Write-Host "[!] Skipping frontend (SKIP_FRONTEND=true)" -ForegroundColor Yellow
    $runFrontend = $false
} elseif (Test-ProcessRunning $FrontendPidFile) {
    $frontendPid = Get-Content $FrontendPidFile
    Write-Host "[!] Frontend already running (PID: $frontendPid)" -ForegroundColor Yellow
    $runFrontend = $false
} else {
    $runFrontend = $true
}

# Exit if all processes are running
if (-not $runApi -and -not $runWorker -and -not $runCrawlWorker -and -not $runClaudeWorker -and -not $runFrontend) {
    Write-Host "`nAll processes are already running." -ForegroundColor Green
    Write-Host "View logs: .\scripts\logs.ps1"
    Write-Host "Stop processes: .\scripts\stop.ps1"
    exit 0
}

# Change working directory
Set-Location $ProjectRoot

# Activate virtual environment if exists
$VenvPath = Join-Path $ProjectRoot "venv\Scripts\Activate.ps1"
$VenvPath2 = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"

if (Test-Path $VenvPath) {
    Write-Host "[*] Activating virtual environment..." -ForegroundColor Cyan
    & $VenvPath
} elseif (Test-Path $VenvPath2) {
    Write-Host "[*] Activating virtual environment..." -ForegroundColor Cyan
    & $VenvPath2
}

# Generate timestamp
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Monitor Page Background Startup" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Start API server (disable auto worker start)
if ($runApi) {
    Write-Host "[*] Starting API server..." -ForegroundColor Cyan

    # Check and clean port
    Stop-ProcessOnPort -Port $ApiPort | Out-Null

    # Set environment variable (disable auto worker start)
    $env:WORKER_AUTO_START = "false"

    $apiLogFile = Join-Path $LogDir "api_$Timestamp.log"

    # Start API server in background
    # stdout/stderr goes to separate files, Python logging goes to api_*.log
    $stdoutLogFile = Join-Path $LogDir "stdout_api_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_api_$Timestamp.log"

    # Set environment variables
    $env:PYTHONIOENCODING = "utf-8"
    $env:APP_MODE = $AppMode

    # Use venv python explicitly
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
    }

    # Start python directly (NOT via cmd.exe) to get correct PID
    # Dev mode: add --reload for hot reload (auto-restart on file changes)
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$ApiPort")
    if ($Dev) {
        $uvicornArgs += @("--reload", "--reload-dir", "app")
        Write-Host "    [*] Hot reload enabled (--reload)" -ForegroundColor Yellow
    }

    $apiProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList $uvicornArgs `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # Save PID - this is now the actual python process PID
    $apiProcess.Id | Out-File $ApiPidFile -Encoding ascii

    Write-Host "[+] API server started (PID: $($apiProcess.Id))" -ForegroundColor Green
    Write-Host "    Port: $ApiPort"
    Write-Host "    Log: $apiLogFile"
}

# Wait for API server initialization
Start-Sleep -Seconds 2

# Start Worker with Watchdog for auto-restart
if ($runWorker) {
    Write-Host "`n[*] Starting Worker with Watchdog..." -ForegroundColor Cyan

    $workerLogFile = Join-Path $LogDir "worker_$Timestamp.log"
    $watchdogLogFile = Join-Path $LogDir "watchdog.log"

    # Start watchdog process which will manage the worker
    # Watchdog monitors worker and restarts it if it crashes
    $watchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\worker-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    # Save Watchdog PID to separate file (worker PID will be managed by watchdog in worker.pid)
    $WatchdogPidFile = Join-Path $PidDir "watchdog$PidSuffix.pid"
    $watchdogProcess.Id | Out-File $WatchdogPidFile -Encoding ascii

    # Wait for worker to actually start
    Start-Sleep -Seconds 2

    Write-Host "[+] Worker Watchdog started (PID: $($watchdogProcess.Id))" -ForegroundColor Green
    Write-Host "    Worker Log: $workerLogFile"
    Write-Host "    Watchdog Log: $watchdogLogFile"
    Write-Host "    [!] Worker will auto-restart if it crashes" -ForegroundColor Yellow
}

# Start Crawl Worker with Watchdog for auto-restart
if ($runCrawlWorker) {
    Write-Host "`n[*] Starting Crawl Worker with Watchdog..." -ForegroundColor Cyan

    $crawlWorkerLogFile = Join-Path $LogDir "crawl_worker_$Timestamp.log"
    $crawlWatchdogLogFile = Join-Path $LogDir "crawl_watchdog.log"

    # Start watchdog process which will manage the Crawl worker
    # Watchdog monitors worker and restarts it if it crashes
    $crawlWatchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\crawl-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    # Save Crawl Watchdog PID (worker PID will be managed by watchdog in crawl_worker.pid)
    $crawlWatchdogProcess.Id | Out-File $CrawlWatchdogPidFile -Encoding ascii

    # Wait for worker to actually start
    Start-Sleep -Seconds 2

    Write-Host "[+] Crawl Watchdog started (PID: $($crawlWatchdogProcess.Id))" -ForegroundColor Green
    Write-Host "    Worker Log: $crawlWorkerLogFile"
    Write-Host "    Watchdog Log: $crawlWatchdogLogFile"
    Write-Host "    [!] Crawl Worker will auto-restart if it crashes" -ForegroundColor Yellow
}

# Start Claude Worker with Watchdog for auto-restart
if ($runClaudeWorker) {
    Write-Host "`n[*] Starting Claude Worker with Watchdog..." -ForegroundColor Cyan

    $claudeWorkerLogFile = Join-Path $LogDir "claude_worker_$Timestamp.log"
    $claudeWatchdogLogFile = Join-Path $LogDir "claude_watchdog.log"

    # Start watchdog process which will manage the Claude worker
    $claudeWatchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\claude-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    # Save Claude Watchdog PID
    $ClaudeWatchdogPidFile = Join-Path $PidDir "claude_watchdog$PidSuffix.pid"
    $claudeWatchdogProcess.Id | Out-File $ClaudeWatchdogPidFile -Encoding ascii

    # Wait for worker to actually start
    Start-Sleep -Seconds 2

    Write-Host "[+] Claude Watchdog started (PID: $($claudeWatchdogProcess.Id))" -ForegroundColor Green
    Write-Host "    Worker Log: $claudeWorkerLogFile"
    Write-Host "    Watchdog Log: $claudeWatchdogLogFile"
    Write-Host "    [!] Claude Worker will auto-restart if it crashes" -ForegroundColor Yellow
}

# Start Frontend
if ($runFrontend) {
    Write-Host "`n[*] Starting Frontend..." -ForegroundColor Cyan

    # Check and clean port
    Stop-ProcessOnPort -Port $FrontendPort | Out-Null

    $frontendLogFile = Join-Path $LogDir "frontend_$Timestamp.log"

    # Check node_modules
    $nodeModules = Join-Path $FrontendDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Host "    [*] Running npm install..." -ForegroundColor Yellow
        $npmInstall = Start-Process -FilePath "npm" `
            -ArgumentList "install" `
            -WorkingDirectory $FrontendDir `
            -Wait `
            -NoNewWindow `
            -PassThru
    }

    if ($Dev) {
        # Dev mode: Run npm run dev in foreground (interactive)
        Write-Host "[+] Frontend starting in DEV mode (foreground)..." -ForegroundColor Green
        Write-Host "    Port: $FrontendPort"
        Write-Host "    API Port: $ApiPort"
        Write-Host "    Exit: Ctrl+C" -ForegroundColor Yellow
        Write-Host ""

        # Store info that frontend is running in dev mode
        "DEV_MODE" | Out-File $FrontendPidFile -Encoding ascii

        # Set API port for vite proxy
        $env:VITE_API_PORT = $ApiPort

        # Save current location and restore after
        Push-Location $FrontendDir
        try {
            npm run dev -- --port $FrontendPort
        } finally {
            Pop-Location
            # When npm run dev exits, clean up
            Remove-Item $FrontendPidFile -Force -ErrorAction SilentlyContinue
            $env:VITE_API_PORT = $null
        }
    } else {
        # Background mode: Start Frontend in background using cmd to redirect both stdout and stderr
        # Set VITE_API_PORT for non-dev mode only if using non-standard port
        $envPrefix = if ($ApiPort -ne 8000) { "set VITE_API_PORT=$ApiPort && " } else { "" }
        $frontendProcess = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "${envPrefix}npm run dev -- --port $FrontendPort > `"$frontendLogFile`" 2>&1" `
            -WorkingDirectory $FrontendDir `
            -WindowStyle Hidden `
            -PassThru

        # Save PID
        $frontendProcess.Id | Out-File $FrontendPidFile -Encoding ascii

        Write-Host "[+] Frontend started (PID: $($frontendProcess.Id))" -ForegroundColor Green
        Write-Host "    Port: $FrontendPort"
        Write-Host "    Log: $frontendLogFile"
    }
}

# Skip summary if we were in Dev mode (frontend ran in foreground and already exited)
if (-not $Dev) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "  All processes started" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Frontend:   http://localhost:$FrontendPort" -ForegroundColor Cyan
    Write-Host "API Server: http://localhost:$ApiPort" -ForegroundColor Cyan
    Write-Host "API Docs:   http://localhost:$ApiPort/docs" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  View logs:    .\scripts\logs.ps1"
    Write-Host "  Stop all:     .\scripts\stop.ps1"
    Write-Host ""
}
