# Monitor Page - Process Stop Script
# Stops FastAPI server, monitoring worker, and Frontend (including zombie processes)

param(
    [switch]$Force  # Skip confirmations
)

# Trap all errors and wait for key before exit
trap {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Press any key to exit..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Port settings
$ApiPort = 8000
$FrontendPort = 5173

# PID file paths
$PidDir = Join-Path $ProjectRoot ".pids"
$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"
$InstagramWorkerPidFile = Join-Path $PidDir "instagram_worker.pid"
$WatchdogPidFile = Join-Path $PidDir "watchdog.pid"
$InstagramWatchdogPidFile = Join-Path $PidDir "instagram_watchdog.pid"
$FrontendPidFile = Join-Path $PidDir "frontend.pid"

Write-Host ""
Write-Host "========================================" -ForegroundColor Red
Write-Host "  Monitor Page Process Stop" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# ============================================================
# STEP 0: Kill All Watchdog Processes (PowerShell)
# ============================================================
Write-Host "[0] Killing Watchdog processes" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$watchdogKilled = 0
$psProcs = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue

if ($psProcs) {
    foreach ($proc in $psProcs) {
        $cmd = $proc.CommandLine
        # Kill both worker-watchdog.ps1 and instagram-watchdog.ps1
        if ($cmd -and ($cmd -match "worker-watchdog\.ps1" -or $cmd -match "instagram-watchdog\.ps1")) {
            $procId = $proc.ProcessId
            $watchdogType = if ($cmd -match "instagram") { "Instagram" } else { "Worker" }
            Write-Host "  [*] $watchdogType Watchdog PID $procId" -ForegroundColor Yellow
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host "      -> Killed" -ForegroundColor Green
                $watchdogKilled++
            } catch {
                Write-Host "      -> Failed: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

if ($watchdogKilled -eq 0) {
    Write-Host "  (no watchdog processes found)" -ForegroundColor Gray
}

Write-Host ""

# ============================================================
# STEP 1: Kill all Python processes matching our patterns
# ============================================================
Write-Host "[1] Killing all monitor-page Python processes" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$pythonKilled = 0

# Get all python processes with their command lines
$pythonProcs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue

if ($pythonProcs) {
    foreach ($proc in $pythonProcs) {
        $cmd = $proc.CommandLine
        if (-not $cmd) { continue }

        # Check if this is a monitor-page related process
        $isOurs = $false
        if ($cmd -match "app\.main" -or
            $cmd -match "app\.worker" -or
            $cmd -match "uvicorn" -or
            $cmd -match "monitor-page") {
            $isOurs = $true
        }

        if ($isOurs) {
            $procId = $proc.ProcessId
            $cmdShort = if ($cmd.Length -gt 70) { $cmd.Substring(0, 70) + "..." } else { $cmd }
            Write-Host "  [*] PID $procId : $cmdShort" -ForegroundColor Yellow

            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host "      -> Killed" -ForegroundColor Green
                $pythonKilled++
            } catch {
                Write-Host "      -> Failed: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

if ($pythonKilled -eq 0) {
    Write-Host "  (no matching processes found)" -ForegroundColor Gray
} else {
    Write-Host "  Total killed: $pythonKilled" -ForegroundColor Green
}

# ============================================================
# STEP 2: Kill processes on our ports
# ============================================================
Write-Host ""
Write-Host "[2] Killing processes on ports $ApiPort, $FrontendPort" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$portKilled = 0
$killedPids = @{}  # Track already killed PIDs to avoid duplicate attempts

foreach ($port in @($ApiPort, $FrontendPort)) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($conn in $conns) {
            $procId = $conn.OwningProcess
            if ($procId -eq 0) { continue }
            if ($killedPids.ContainsKey($procId)) { continue }  # Skip already killed

            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "  [*] Port $port : $($proc.ProcessName) (PID $procId)" -ForegroundColor Yellow
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                    Write-Host "      -> Killed" -ForegroundColor Green
                    $portKilled++
                    $killedPids[$procId] = $true  # Mark as killed
                } catch {
                    Write-Host "      -> Failed: $($_.Exception.Message)" -ForegroundColor Red
                }
            }
        }
    }
}

if ($portKilled -eq 0) {
    Write-Host "  (no processes on these ports)" -ForegroundColor Gray
}

# ============================================================
# STEP 3: Kill Node/Vite processes
# ============================================================
Write-Host ""
Write-Host "[3] Killing Vite/Node processes" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$nodeKilled = 0
$nodeProcs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue

if ($nodeProcs) {
    foreach ($proc in $nodeProcs) {
        $cmd = $proc.CommandLine
        if ($cmd -and $cmd -match "vite") {
            $procId = $proc.ProcessId
            Write-Host "  [*] PID $procId : vite dev server" -ForegroundColor Yellow
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Host "      -> Killed" -ForegroundColor Green
                $nodeKilled++
            } catch {
                Write-Host "      -> Failed: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

if ($nodeKilled -eq 0) {
    Write-Host "  (no vite processes found)" -ForegroundColor Gray
}

# ============================================================
# STEP 4: Clean up PID files
# ============================================================
Write-Host ""
Write-Host "[4] Cleaning up PID files" -ForegroundColor Cyan
Write-Host "----------------------------------------"

foreach ($pidFile in @($ApiPidFile, $WorkerPidFile, $InstagramWorkerPidFile, $WatchdogPidFile, $InstagramWatchdogPidFile, $FrontendPidFile)) {
    if (Test-Path $pidFile) {
        $name = Split-Path $pidFile -Leaf
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "  [+] Deleted: $name" -ForegroundColor Green
    }
}

# ============================================================
# STEP 5: Browser cleanup (optional)
# ============================================================
Write-Host ""
Write-Host "[5] Checking Chrome processes" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$browserDataPath = Join-Path $ProjectRoot "browser_data"
$chromeProcs = Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -like "*$browserDataPath*"
}

if ($chromeProcs) {
    $count = @($chromeProcs).Count
    Write-Host "  Found $count Chrome process(es) for monitoring" -ForegroundColor Yellow

    $doKill = $Force
    if (-not $Force) {
        $response = Read-Host "  Kill them? (y/N)"
        $doKill = ($response -eq "y" -or $response -eq "Y")
    }

    if ($doKill) {
        foreach ($chrome in $chromeProcs) {
            try {
                Stop-Process -Id $chrome.ProcessId -Force -ErrorAction Stop
                Write-Host "  [+] Killed Chrome PID $($chrome.ProcessId)" -ForegroundColor Green
            } catch {
                Write-Host "  [-] Failed to kill Chrome PID $($chrome.ProcessId)" -ForegroundColor Red
            }
        }
    }
} else {
    Write-Host "  (no monitoring Chrome processes)" -ForegroundColor Gray
}

# Clean browser lock file
$lockFile = Join-Path $browserDataPath "browser_profile\lockfile"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Write-Host "  [+] Deleted browser lockfile" -ForegroundColor Green
}

# ============================================================
# DONE
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Stop complete" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
