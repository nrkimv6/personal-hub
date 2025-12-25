# Monitor Page - Service Runner Script
# This script is designed to run as a Windows service via NSSM
#
# It performs the same initialization as run.ps1 but:
# - Runs API server in foreground (NSSM monitors this process)
# - Starts Frontend/Workers in background via start.ps1
# - Properly cleans up on exit via stop.ps1
#
# This ensures all the cleanup logic from run.ps1 is preserved.

param(
    [switch]$Dev  # Dev mode: different ports + workers
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Mode and port settings
if ($Dev) {
    $ApiPort = 8001
    $FrontendPort = 5174
    $AppMode = "development"
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    $PidSuffix = "_dev"
    $RunWorkers = $true
} else {
    $ApiPort = 8000
    $FrontendPort = 5173
    $AppMode = "production"
    $LogDir = Join-Path $ProjectRoot "logs"
    $PidSuffix = ""
    $RunWorkers = $false
}

# Ensure directories exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$PidDir = Join-Path $ProjectRoot ".pids"
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# Service-specific log file (separate from app logs)
$serviceLogFile = Join-Path $LogDir "service_runner.log"

function Write-ServiceLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] $Message"
    Add-Content -Path $serviceLogFile -Value $logLine -Encoding UTF8
    Write-Host $logLine
}

Write-ServiceLog "=========================================="
Write-ServiceLog "Monitor Page Service Starting"
Write-ServiceLog "Mode: $AppMode"
Write-ServiceLog "API Port: $ApiPort, Frontend Port: $FrontendPort"
Write-ServiceLog "Workers: $(if ($RunWorkers) { 'ON' } else { 'OFF' })"
Write-ServiceLog "=========================================="

# Set environment variables
$env:APP_MODE = $AppMode
$env:PYTHONIOENCODING = "utf-8"

# ============================================================
# STEP 1: Port Cleanup (from run.ps1)
# ============================================================
Write-ServiceLog "Cleaning up ports..."
$portsToClean = @($ApiPort, $FrontendPort)
foreach ($port in $portsToClean) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-ServiceLog "Killing zombie process on port ${port}: $($proc.ProcessName) (PID: $procId)"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 300
            }
        }
    }
}

# ============================================================
# STEP 2: Playwright Browser Cleanup (Dev mode only, from run.ps1)
# ============================================================
if ($RunWorkers) {
    $browserProfilesPath = Join-Path $ProjectRoot "data\browser_profiles"

    Write-ServiceLog "Cleaning up Playwright browsers..."

    # Kill orphaned Playwright chromium processes (not regular Chrome)
    $chromeProcs = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
    $killedCount = 0
    foreach ($proc in $chromeProcs) {
        try {
            $procPath = $proc.Path
            if ($procPath -and $procPath -like "*ms-playwright*") {
                Write-ServiceLog "Killing orphaned Playwright browser (PID: $($proc.Id))"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $killedCount++
            }
        } catch {
            # Ignore access denied errors for system processes
        }
    }
    if ($killedCount -gt 0) {
        Write-ServiceLog "Killed $killedCount Playwright browser process(es)"
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
                Write-ServiceLog "Cleaned up $cleanedCount LOCK file(s)"
            }
        }

        # Clean Crashpad data
        $crashpadDirs = Get-ChildItem -Path $browserProfilesPath -Directory -Filter "Crashpad" -Recurse -ErrorAction SilentlyContinue
        foreach ($crashpad in $crashpadDirs) {
            Remove-Item -Path "$($crashpad.FullName)\*" -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($crashpadDirs) {
            Write-ServiceLog "Cleaned up Crashpad data"
        }
    }
}

# ============================================================
# STEP 3: Start Background Processes (Frontend, Workers via Watchdog)
# ============================================================
Write-ServiceLog "Starting background processes..."

$startScript = Join-Path $ScriptDir "start.ps1"
$stopScript = Join-Path $ScriptDir "stop.ps1"

# Set environment to skip API (we'll run it in foreground) but start everything else
# For Production: Frontend only (no workers)
# For Dev: Frontend + all workers via watchdog
if ($RunWorkers) {
    # Dev mode: start everything except API
    $env:SKIP_WORKER = $null
    $env:SKIP_INSTAGRAM_WORKER = $null
    $env:SKIP_CLAUDE_WORKER = $null
} else {
    # Production mode: skip all workers
    $env:SKIP_WORKER = "true"
    $env:SKIP_INSTAGRAM_WORKER = "true"
    $env:SKIP_CLAUDE_WORKER = "true"
}

# We handle API ourselves, skip it in start.ps1
# Unfortunately start.ps1 doesn't have a SKIP_API flag, so we need to handle this differently

# Actually, let's start Frontend and Workers separately
# This gives us more control

# ---- Start Frontend ----
Write-ServiceLog "Starting Frontend..."
$FrontendDir = Join-Path $ProjectRoot "frontend"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$frontendLogFile = Join-Path $LogDir "frontend_$Timestamp.log"
$FrontendPidFile = Join-Path $PidDir "frontend$PidSuffix.pid"

# Check node_modules
$nodeModules = Join-Path $FrontendDir "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-ServiceLog "Running npm install..."
    $npmResult = Start-Process -FilePath "npm" -ArgumentList "install" -WorkingDirectory $FrontendDir -Wait -NoNewWindow -PassThru
    if ($npmResult.ExitCode -ne 0) {
        Write-ServiceLog "WARNING: npm install failed with exit code $($npmResult.ExitCode)"
    }
}

$envPrefix = if ($ApiPort -ne 8000) { "set VITE_API_PORT=$ApiPort && " } else { "" }
$frontendProcess = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "${envPrefix}npm run dev -- --host --port $FrontendPort > `"$frontendLogFile`" 2>&1" `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -PassThru

$frontendProcess.Id | Out-File $FrontendPidFile -Encoding ascii
Write-ServiceLog "Frontend started (PID: $($frontendProcess.Id))"

# ---- Start Workers (Dev mode only, via Watchdog) ----
if ($RunWorkers) {
    # Worker Watchdog
    Write-ServiceLog "Starting Worker Watchdog..."
    $WatchdogPidFile = Join-Path $PidDir "watchdog$PidSuffix.pid"
    $watchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\worker-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    $watchdogProcess.Id | Out-File $WatchdogPidFile -Encoding ascii
    Write-ServiceLog "Worker Watchdog started (PID: $($watchdogProcess.Id))"

    # Instagram Worker Watchdog
    Write-ServiceLog "Starting Instagram Watchdog..."
    $InstagramWatchdogPidFile = Join-Path $PidDir "instagram_watchdog$PidSuffix.pid"
    $igWatchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\instagram-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    $igWatchdogProcess.Id | Out-File $InstagramWatchdogPidFile -Encoding ascii
    Write-ServiceLog "Instagram Watchdog started (PID: $($igWatchdogProcess.Id))"

    # Claude Worker Watchdog
    Write-ServiceLog "Starting Claude Watchdog..."
    $ClaudeWatchdogPidFile = Join-Path $PidDir "claude_watchdog$PidSuffix.pid"
    $claudeWatchdogProcess = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\claude-watchdog.ps1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    $claudeWatchdogProcess.Id | Out-File $ClaudeWatchdogPidFile -Encoding ascii
    Write-ServiceLog "Claude Watchdog started (PID: $($claudeWatchdogProcess.Id))"

    Start-Sleep -Seconds 2
}

# ============================================================
# STEP 4: Run API Server in Foreground (NSSM monitors this)
# ============================================================
Write-ServiceLog "Starting API Server in foreground..."

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
}

$ApiPidFile = Join-Path $PidDir "api$PidSuffix.pid"
$apiLogFile = Join-Path $LogDir "api_$Timestamp.log"
$stdoutLogFile = Join-Path $LogDir "stdout_api_$Timestamp.log"
$stderrLogFile = Join-Path $LogDir "stderr_api_$Timestamp.log"

# Set WORKER_AUTO_START=false to prevent API from spawning its own workers
$env:WORKER_AUTO_START = "false"

try {
    # Start API and wait for it (this is the main process NSSM watches)
    $apiProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", $ApiPort `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # Save PID
    $apiProcess.Id | Out-File $ApiPidFile -Encoding ascii
    Write-ServiceLog "API Server started (PID: $($apiProcess.Id))"
    Write-ServiceLog "Waiting for API Server to exit..."

    # Wait for API process to exit
    $apiProcess.WaitForExit()
    $exitCode = $apiProcess.ExitCode

    Write-ServiceLog "API Server exited with code: $exitCode"

} catch {
    Write-ServiceLog "API Server failed: $_"
    $exitCode = 1
} finally {
    # ============================================================
    # STEP 5: Cleanup on Exit (via stop.ps1)
    # ============================================================
    Write-ServiceLog "Service stopping, running cleanup..."

    # Use stop.ps1 to properly clean up all processes
    try {
        if ($Dev) {
            & $stopScript -Force -Dev 2>&1 | ForEach-Object { Write-ServiceLog $_ }
        } else {
            & $stopScript -Force 2>&1 | ForEach-Object { Write-ServiceLog $_ }
        }
    } catch {
        Write-ServiceLog "Cleanup error: $_"
    }

    Write-ServiceLog "Service stopped"
}

exit $exitCode
