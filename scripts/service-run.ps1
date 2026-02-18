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
    $FrontendPort = 6101
    $AppMode = "development"
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    $PidSuffix = "_dev"
} else {
    $ApiPort = 8000
    $FrontendPort = 6100
    $AppMode = "production"
    $LogDir = Join-Path $ProjectRoot "logs"
    $PidSuffix = ""
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
# STEP 0: Redis - DISABLED (Session 0 Constraint)
# ============================================================
# Redis는 startup-browser-workers.ps1에서 시작됨 (사용자 세션 필요)
#
# NSSM 서비스는 Session 0 (시스템 세션)에서 실행되어:
#   - Podman Machine (WSL2 VM)이 사용자 로그인 후에만 초기화됨
#   - "Cannot connect to Podman" 에러 발생 → SQLite 폴백
#
# Redis는 로그인 시작프로그램 (Session 1)에서 시작:
#   - startup-browser-workers.ps1 → Redis 시작 → browser-workers.ps1
#   - 참고: docs/auto-start/2026-01-09-redis-server-failure-analysis.md
#
# API는 Redis 없이 정상 동작 (SQLite 폴백 모드)
Write-ServiceLog "Redis will be started via startup program (requires user session)"

# ============================================================
# Helper: netstat 기반 포트 PID 조회 (Session 0에서 Get-NetTCPConnection 행 방지)
# ============================================================
function Get-ListeningPids {
    param([int]$Port)
    $pids = @()
    try {
        $lines = netstat -ano 2>$null | Select-String ":${Port}\s+.*LISTENING"
        foreach ($line in $lines) {
            if ($line -match '\s(\d+)\s*$') {
                $pid = [int]$Matches[1]
                if ($pid -ne 0 -and $pids -notcontains $pid) {
                    $pids += $pid
                }
            }
        }
    } catch {
        Write-ServiceLog "  WARNING: netstat failed for port ${Port}: $_"
    }
    return $pids
}

# ============================================================
# STEP 0.5: Stale PID / Orphan Process Cleanup
# ============================================================
Write-ServiceLog "Checking for stale PID files and orphan processes..."

# (a) Stale PID 파일 기반 고아 프로세스 정리
if (Test-Path $PidDir) {
    $pidFiles = Get-ChildItem -Path $PidDir -Filter "*.pid" -ErrorAction SilentlyContinue
    foreach ($pidFile in $pidFiles) {
        $stalePid = (Get-Content $pidFile.FullName -ErrorAction SilentlyContinue).Trim()
        if ($stalePid -and $stalePid -match '^\d+$') {
            $proc = Get-Process -Id ([int]$stalePid) -ErrorAction SilentlyContinue
            if ($proc) {
                Write-ServiceLog "  Killing orphan process: $($proc.ProcessName) (PID: $stalePid) from $($pidFile.Name)"
                Stop-Process -Id ([int]$stalePid) -Force -ErrorAction SilentlyContinue
            } else {
                Write-ServiceLog "  Cleaned stale PID file: $($pidFile.Name) (PID $stalePid no longer exists)"
            }
            Remove-Item $pidFile.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# (b) Vite 고아 프로세스 탐지 (잘못된 포트의 Vite 프로세스 제거)
try {
    $nodeProcs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue
    foreach ($np in $nodeProcs) {
        if ($np.CommandLine -and $np.CommandLine -match 'vite' -and $np.CommandLine -notmatch "--port\s+$FrontendPort") {
            Write-ServiceLog "  Killing orphan Vite process (PID: $($np.ProcessId), Cmd: $($np.CommandLine.Substring(0, [Math]::Min(80, $np.CommandLine.Length)))...)"
            Stop-Process -Id $np.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    Write-ServiceLog "  WARNING: Vite orphan check failed: $_"
}

# ============================================================
# STEP 1: Port Cleanup (improved with graceful shutdown)
# ============================================================
Write-ServiceLog "Cleaning up ports..."
$portsToClean = @($ApiPort, $FrontendPort)
$maxRetries = 3
$retryDelayMs = 500
$gracefulTimeoutMs = 2000

foreach ($port in $portsToClean) {
    for ($retry = 0; $retry -lt $maxRetries; $retry++) {
        # netstat 기반으로 Listen 중인 PID 조회 (Session 0 호환)
        $pids = Get-ListeningPids -Port $port

        if ($pids.Count -eq 0) {
            Write-ServiceLog "  Port ${port}: available"
            break
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

    # 최종 확인 (netstat 기반)
    $remainingPids = Get-ListeningPids -Port $port
    if ($remainingPids.Count -gt 0) {
        Write-ServiceLog "  WARNING: Port ${port} still in use after cleanup (PIDs: $($remainingPids -join ', '))"
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

# Start frontend - different modes for dev/production
if ($Dev) {
    # ---- Development: npm run dev (HMR, hot reload) ----
    # Stale build 디렉토리 제거 (lstat 에러 방지)
    $buildDir = Join-Path $FrontendDir "build"
    if (Test-Path $buildDir) {
        Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-ServiceLog "Cleaned up stale build directory"
    }

    # Set environment variable for Vite (non-default API port)
    $env:VITE_API_PORT = $ApiPort
    # Write to .env.development.local (only loaded in Vite dev mode)
    $envDevLocalFile = Join-Path $FrontendDir ".env.development.local"
    "VITE_API_PORT=$ApiPort" | Out-File $envDevLocalFile -Encoding utf8
    Write-ServiceLog "Created .env.development.local with VITE_API_PORT=$ApiPort"

    $frontendProcess = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev", "--", "--host", "--port", $FrontendPort `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLogFile `
        -RedirectStandardError $frontendErrLogFile `
        -PassThru
} else {
    # ---- Production: npm run build + npm run preview ----
    # Remove .env.local if exists (prevents dev settings from affecting production)
    $envLocalFile = Join-Path $FrontendDir ".env.local"
    if (Test-Path $envLocalFile) {
        Remove-Item $envLocalFile -Force
        Write-ServiceLog "Removed .env.local"
    }

    # Build frontend using cmd.exe for proper output redirection
    Write-ServiceLog "Building frontend for production..."
    $buildLogFile = Join-Path $LogDir "frontend_build_$Timestamp.log"

    # Use cmd /c to run npm build with output redirection
    $buildResult = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "cd /d `"$FrontendDir`" && npm run build > `"$buildLogFile`" 2>&1" `
        -Wait -WindowStyle Hidden `
        -PassThru

    if ($buildResult.ExitCode -ne 0) {
        Write-ServiceLog "ERROR: Frontend build failed (exit code: $($buildResult.ExitCode))"
        Write-ServiceLog "Check build log: $buildLogFile"
        # Show last few lines of build log
        if (Test-Path $buildLogFile) {
            $lastLines = Get-Content $buildLogFile -Tail 10
            foreach ($line in $lastLines) {
                Write-ServiceLog "  $line"
            }
        }
        exit 1
    }
    Write-ServiceLog "Frontend build completed"

    # Start preview server
    Write-ServiceLog "Starting frontend preview server..."
    $frontendProcess = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "preview", "--", "--host", "--port", $FrontendPort `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLogFile `
        -RedirectStandardError $frontendErrLogFile `
        -PassThru
}

$frontendProcess.Id | Out-File $FrontendPidFile -Encoding ascii
Write-ServiceLog "Frontend started (PID: $($frontendProcess.Id))"

# ---- Workers Note ----
# All browser-based workers are NOT started here.
# NSSM service runs in Session 0, which cannot use headed browsers.
#
# Workers are started via startup program (user session):
#   - Startup program: startup-browser-workers.ps1 (auto on login)
#   - Manual: browser-workers.ps1 -Action start
#
# Workers that require user session (headed browser):
#   - monitor_worker: Uses Playwright browser for Naver booking
#   - crawl_worker: Uses Playwright browser for Instagram
#   - claude_worker: Uses Playwright browser for web scraping
#
# See: docs/auto-start/README.md
Write-ServiceLog "All workers will be started via startup program (requires user session)"

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

# Set API_PORT for programmatic uvicorn (app/main.py __main__ block)
$env:API_PORT = $ApiPort

try {
    # Programmatic uvicorn: python -m app.main
    # (서버 인스턴스를 app.core.server_state에 저장하여 self-restart에서
    #  server.should_exit = True 로 graceful shutdown 가능)
    # CLI uvicorn (python -m uvicorn) 대비 장점:
    #   - server.should_exit: uvicorn 공식 graceful shutdown 경로
    #   - timeout_graceful_shutdown=30: shutdown 타임아웃 설정
    #   - signal.raise_signal(SIGINT) 의 Windows 호환성 이슈 회피
    $uvicornArgs = @("-m", "app.main")
    if ($Dev) {
        # Hot reload disabled - causes hang in Windows NSSM environment (Session 0)
        # See: docs/2026-01-04-api-stability-improvements.md
        # Manual reload: browser-workers.ps1 -Action restart-api
        Write-ServiceLog "Development mode (manual reload required - hot reload disabled for stability)"
    }

    # Start API and wait for it (this is the main process NSSM watches)
    # Set environment variables before starting process (PowerShell 5.1 compatible)
    $env:API_PORT = $ApiPort
    $env:WORKER_AUTO_START = "false"
    $env:APP_MODE = $AppMode
    $env:PYTHONIOENCODING = "utf-8"

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

    # Heartbeat 루프로 API 프로세스 대기 (행 감지 용이화)
    $heartbeatInterval = 30  # 초
    while (-not $apiProcess.HasExited) {
        Start-Sleep -Seconds $heartbeatInterval
        if (-not $apiProcess.HasExited) {
            Write-ServiceLog "Heartbeat: API running (PID: $($apiProcess.Id), Uptime: $([int](New-TimeSpan -Start $apiProcess.StartTime -End (Get-Date)).TotalMinutes)m)"
        }
    }
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
    # -SkipWatchdog: Don't kill watchdog processes (they run in user session, not service)
    # -SkipWorkers: Don't kill worker processes (they run separately via browser-workers.ps1)
    try {
        if ($Dev) {
            & $stopScript -Force -Dev -SkipWatchdog -SkipWorkers 2>&1 | ForEach-Object { Write-ServiceLog $_ }
        } else {
            & $stopScript -Force -SkipWatchdog -SkipWorkers 2>&1 | ForEach-Object { Write-ServiceLog $_ }
        }
    } catch {
        Write-ServiceLog "Cleanup error: $_"
    }

    Write-ServiceLog "Service stopped"
}

exit $exitCode
