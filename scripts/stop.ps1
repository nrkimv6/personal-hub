# Monitor Page - Process Stop Script
# Stops FastAPI server, monitoring worker, and Frontend (including zombie processes)

param(
    [switch]$Force,  # Skip confirmations
    [switch]$Dev,    # Stop dev environment (ports 8001, 5174)
    [switch]$All     # Stop both dev and production environments
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

# Port settings based on mode
if ($All) {
    $ApiPorts = @(8000, 8001)
    $FrontendPorts = @(5173, 5174)
    $PidSuffixes = @("", "_dev")
    Write-Host "[MODE] Stopping ALL environments (production + dev)" -ForegroundColor Yellow
} elseif ($Dev) {
    $ApiPorts = @(8001)
    $FrontendPorts = @(5174)
    $PidSuffixes = @("_dev")
    Write-Host "[MODE] Stopping DEV environment only" -ForegroundColor Yellow
} else {
    $ApiPorts = @(8000)
    $FrontendPorts = @(5173)
    $PidSuffixes = @("")
    Write-Host "[MODE] Stopping PRODUCTION environment only" -ForegroundColor Yellow
}

# PID file paths (collect all based on mode)
$PidDir = Join-Path $ProjectRoot ".pids"
$PidFiles = @()
foreach ($suffix in $PidSuffixes) {
    $PidFiles += Join-Path $PidDir "api$suffix.pid"
    $PidFiles += Join-Path $PidDir "worker$suffix.pid"
    $PidFiles += Join-Path $PidDir "instagram_worker$suffix.pid"
    $PidFiles += Join-Path $PidDir "claude_worker$suffix.pid"
    $PidFiles += Join-Path $PidDir "watchdog$suffix.pid"
    $PidFiles += Join-Path $PidDir "instagram_watchdog$suffix.pid"
    $PidFiles += Join-Path $PidDir "claude_watchdog$suffix.pid"
    $PidFiles += Join-Path $PidDir "frontend$suffix.pid"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Red
Write-Host "  Monitor Page Process Stop" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# ============================================================
# STEP 0: Kill Watchdog Processes (only for target environment)
# ============================================================
$envLabel = if ($All) { "all environments" } elseif ($Dev) { "dev" } else { "production" }
Write-Host "[0] Killing Watchdog processes ($envLabel)" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$watchdogKilled = 0

# Get target watchdog PIDs from PID files
$targetWatchdogPids = @()
foreach ($pidFile in $PidFiles) {
    if ((Test-Path $pidFile) -and $pidFile -match "watchdog") {
        $savedPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $targetWatchdogPids += [int]$savedPid
        }
    }
}

if ($targetWatchdogPids.Count -gt 0) {
    foreach ($procId in $targetWatchdogPids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  [*] Watchdog PID $procId" -ForegroundColor Yellow
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
    Write-Host "  (no watchdog processes found for $envLabel)" -ForegroundColor Gray
}

Write-Host ""

# ============================================================
# STEP 1: Kill Python processes matching our patterns AND ports
# ============================================================
Write-Host "[1] Killing monitor-page Python processes (ports: $($ApiPorts -join ', '))" -ForegroundColor Cyan
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
            # Check if this process belongs to the target environment (by port)
            $isTargetEnv = $false
            foreach ($port in $ApiPorts) {
                if ($cmd -match "--port\s+$port" -or $cmd -match "--port=$port") {
                    $isTargetEnv = $true
                    break
                }
            }
            # Worker processes don't have port in command line, check PID files
            if (-not $isTargetEnv -and ($cmd -match "app\.worker" -or $cmd -match "worker\.py")) {
                # Check if this worker's PID matches our PID files
                foreach ($pidFile in $PidFiles) {
                    if ((Test-Path $pidFile) -and $pidFile -match "worker") {
                        $savedPid = Get-Content $pidFile -ErrorAction SilentlyContinue
                        if ($savedPid -eq $proc.ProcessId) {
                            $isTargetEnv = $true
                            break
                        }
                    }
                }
            }

            if ($isTargetEnv) {
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
$allPorts = $ApiPorts + $FrontendPorts
Write-Host "[2] Killing processes on ports $($allPorts -join ', ')" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$portKilled = 0
$killedPids = @{}  # Track already killed PIDs to avoid duplicate attempts

foreach ($port in $allPorts) {
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
# STEP 3: Kill Node/Vite processes (only for target ports)
# ============================================================
Write-Host ""
Write-Host "[3] Killing Vite/Node processes (ports: $($FrontendPorts -join ', '))" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$nodeKilled = 0
$nodeProcs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue

if ($nodeProcs) {
    foreach ($proc in $nodeProcs) {
        $cmd = $proc.CommandLine
        if ($cmd -and $cmd -match "vite") {
            # Check if this vite process belongs to the target environment (by port)
            $isTargetEnv = $false
            foreach ($port in $FrontendPorts) {
                if ($cmd -match "--port\s+$port" -or $cmd -match "--port=$port" -or $cmd -match "--port `"$port`"") {
                    $isTargetEnv = $true
                    break
                }
            }

            if ($isTargetEnv) {
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
}

if ($nodeKilled -eq 0) {
    Write-Host "  (no vite processes found for target ports)" -ForegroundColor Gray
}

# ============================================================
# STEP 4: Clean up PID files
# ============================================================
Write-Host ""
Write-Host "[4] Cleaning up PID files" -ForegroundColor Cyan
Write-Host "----------------------------------------"

foreach ($pidFile in $PidFiles) {
    if (Test-Path $pidFile) {
        $name = Split-Path $pidFile -Leaf
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "  [+] Deleted: $name" -ForegroundColor Green
    }
}

# ============================================================
# STEP 5: Playwright Browser Cleanup (Kill + Wait + Clean LOCK)
# ============================================================
Write-Host ""
Write-Host "[5] Cleaning up Playwright browsers" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$browserProfilesPath = Join-Path $ProjectRoot "data\browser_profiles"

# 5-1: Kill Playwright Chromium processes (identified by ms-playwright path)
$playwrightKilled = 0
$chromeProcs = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
foreach ($proc in $chromeProcs) {
    try {
        $procPath = $proc.Path
        if ($procPath -and $procPath -like "*ms-playwright*") {
            Write-Host "  [*] Killing Playwright browser (PID: $($proc.Id))" -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            $playwrightKilled++
        }
    } catch {
        # Ignore access denied errors
    }
}

if ($playwrightKilled -gt 0) {
    Write-Host "  [+] Killed $playwrightKilled Playwright browser process(es)" -ForegroundColor Green
    # Wait for processes to fully terminate
    Write-Host "  [*] Waiting for processes to terminate..." -ForegroundColor Gray
    Start-Sleep -Milliseconds 1000
} else {
    Write-Host "  (no Playwright browser processes)" -ForegroundColor Gray
}

# 5-2: Clean up LOCK files in browser profiles
if (Test-Path $browserProfilesPath) {
    $lockFiles = Get-ChildItem -Path $browserProfilesPath -Filter "LOCK" -Recurse -ErrorAction SilentlyContinue
    if ($lockFiles) {
        $lockCount = 0
        foreach ($lockFile in $lockFiles) {
            try {
                Remove-Item $lockFile.FullName -Force -ErrorAction Stop
                $lockCount++
            } catch {
                Write-Host "  [-] Failed to delete: $($lockFile.FullName)" -ForegroundColor Red
            }
        }
        if ($lockCount -gt 0) {
            Write-Host "  [+] Deleted $lockCount LOCK file(s)" -ForegroundColor Green
        }
    } else {
        Write-Host "  (no LOCK files found)" -ForegroundColor Gray
    }

    # 5-3: Clean up Crashpad data (can cause issues on restart)
    $crashpadDirs = Get-ChildItem -Path $browserProfilesPath -Directory -Filter "Crashpad" -Recurse -ErrorAction SilentlyContinue
    foreach ($crashpad in $crashpadDirs) {
        Remove-Item -Path "$($crashpad.FullName)\*" -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($crashpadDirs) {
        Write-Host "  [+] Cleaned up Crashpad data" -ForegroundColor Green
    }
}

# ============================================================
# DONE
# ============================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Stop complete" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Only wait for key press if not in Force mode (interactive use)
if (-not $Force) {
    Write-Host "Press any key to exit..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
