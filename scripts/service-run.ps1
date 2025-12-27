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
# STEP 0: Port Cleanup (improved with graceful shutdown)
# ============================================================
Write-ServiceLog "Cleaning up ports..."
$portsToClean = @($ApiPort, $FrontendPort)
$maxRetries = 3
$retryDelayMs = 500
$gracefulTimeoutMs = 2000

foreach ($port in $portsToClean) {
    for ($retry = 0; $retry -lt $maxRetries; $retry++) {
        # Listen 상태인 연결만 필터링
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

        if (-not $conn) {
            Write-ServiceLog "  Port ${port}: available"
            break
        }

        # PID 0 제외 (커널/시스템)
        $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne 0 }

        if ($pids.Count -eq 0) {
            Write-ServiceLog "  Port ${port}: in use by system (waiting...)"
            Start-Sleep -Milliseconds $retryDelayMs
            continue
        }

        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-ServiceLog "  Port ${port}: stopping $($proc.ProcessName) (PID: $procId) gracefully..."

                # Graceful shutdown 시도 (CloseMainWindow)
                try {
                    $closed = $proc.CloseMainWindow()
                    if ($closed) {
                        # 프로세스가 종료될 때까지 대기 (최대 2초)
                        $exited = $proc.WaitForExit($gracefulTimeoutMs)
                        if ($exited) {
                            Write-ServiceLog "    -> Gracefully stopped"
                            continue
                        }
                    }
                } catch {
                    # CloseMainWindow 실패 시 무시
                }

                # Graceful 실패 시 Force 사용
                Write-ServiceLog "    -> Graceful failed, forcing..."
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }

        Start-Sleep -Milliseconds $retryDelayMs

        if ($retry -lt $maxRetries - 1) {
            Write-ServiceLog "  Port ${port}: retry $($retry + 1)/$maxRetries"
        }
    }

    # 최종 확인
    $stillUsed = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($stillUsed) {
        Write-ServiceLog "  WARNING: Port ${port} still in use after cleanup"
    }
}

# ============================================================
# STEP 1: Playwright Browser Cleanup (Dev mode only, from run.ps1)
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
# STEP 2: Start Background Processes (Frontend, Workers via Watchdog)
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
    $env:SKIP_CRAWL_WORKER = $null
    $env:SKIP_CLAUDE_WORKER = $null
} else {
    # Production mode: skip all workers
    $env:SKIP_WORKER = "true"
    $env:SKIP_CRAWL_WORKER = "true"
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
$frontendErrLogFile = Join-Path $LogDir "frontend_err_$Timestamp.log"
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

# Set environment variable for Vite (non-default API port)
if ($ApiPort -ne 8000) {
    $env:VITE_API_PORT = $ApiPort
    # Also write to .env.local for Vite to pick up (Start-Process may not inherit env vars)
    $envLocalFile = Join-Path $FrontendDir ".env.local"
    "VITE_API_PORT=$ApiPort" | Out-File $envLocalFile -Encoding utf8
    Write-ServiceLog "Created .env.local with VITE_API_PORT=$ApiPort"
}

# Start frontend using npm.cmd directly (avoid cmd.exe socket inheritance issue)
$frontendProcess = Start-Process -FilePath "npm.cmd" `
    -ArgumentList "run", "dev", "--", "--host", "--port", $FrontendPort `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $frontendLogFile `
    -RedirectStandardError $frontendErrLogFile `
    -PassThru

$frontendProcess.Id | Out-File $FrontendPidFile -Encoding ascii
Write-ServiceLog "Frontend started (PID: $($frontendProcess.Id))"

# ---- Start Workers (Dev mode only) ----
if ($RunWorkers) {
    # Note: Browser-based workers (monitor_worker, crawl_worker) are NOT started here.
    # They require user session (headed browser) and are started via:
    #   - Startup program: startup-browser-workers.ps1 (auto on login)
    #   - Manual: browser-workers.ps1 -Action start
    #
    # Workers that require user session:
    #   - monitor_worker: Uses Playwright browser
    #   - crawl_worker: Uses Playwright browser
    #   - llm_worker: Uses Claude CLI which requires user session for login credentials
    #
    # See: docs/auto-start/2025-12-27-browser-worker-separation.md
    Write-ServiceLog "Browser workers (monitor, crawl) will be started via startup program"

    # Claude Worker Watchdog (no browser needed - uses CLI subprocess)
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
# STEP 3: Run API Server in Foreground (NSSM monitors this)
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
    # Build uvicorn arguments
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", $ApiPort)
    if ($Dev) {
        $uvicornArgs += "--reload"
        Write-ServiceLog "Hot reload enabled for development mode"
    }

    # Start API and wait for it (this is the main process NSSM watches)
    $apiProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList $uvicornArgs `
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
    # STEP 4: Cleanup on Exit (via stop.ps1)
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
