# Monitor Page - Background Process Startup Script
# Starts FastAPI server, monitoring worker, and Frontend in background

param(
    [switch]$Dev  # Use 'npm run dev' instead of background mode for frontend
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $ProjectRoot "frontend"

# Port settings
$ApiPort = 8000
$FrontendPort = 5173

# Create log directory
$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# PID file paths
$PidDir = Join-Path $ProjectRoot ".pids"
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"
$FrontendPidFile = Join-Path $PidDir "frontend.pid"

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
if (-not $runApi -and -not $runWorker -and -not $runFrontend) {
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
    # stdout/stderr goes to separate file (stdout_api_*.log), Python logging goes to api_*.log
    $stdoutLogFile = Join-Path $LogDir "stdout_api_$Timestamp.log"
    $apiProcess = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "set PYTHONIOENCODING=utf-8 && python -m uvicorn app.main:app --host 0.0.0.0 --port $ApiPort > `"$stdoutLogFile`" 2>&1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    # Save PID
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
    $WatchdogPidFile = Join-Path $PidDir "watchdog.pid"
    $watchdogProcess.Id | Out-File $WatchdogPidFile -Encoding ascii

    # Wait for worker to actually start
    Start-Sleep -Seconds 2

    Write-Host "[+] Worker Watchdog started (PID: $($watchdogProcess.Id))" -ForegroundColor Green
    Write-Host "    Worker Log: $workerLogFile"
    Write-Host "    Watchdog Log: $watchdogLogFile"
    Write-Host "    [!] Worker will auto-restart if it crashes" -ForegroundColor Yellow
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
        Write-Host "    Exit: Ctrl+C" -ForegroundColor Yellow
        Write-Host ""

        # Store info that frontend is running in dev mode
        "DEV_MODE" | Out-File $FrontendPidFile -Encoding ascii

        # Save current location and restore after
        Push-Location $FrontendDir
        try {
            npm run dev -- --port $FrontendPort
        } finally {/
            Pop-Location
            # When npm run dev exits, clean up
            Remove-Item $FrontendPidFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        # Background mode: Start Frontend in background using cmd to redirect both stdout and stderr
        $frontendProcess = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "npm run dev -- --port $FrontendPort > `"$frontendLogFile`" 2>&1" `
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
