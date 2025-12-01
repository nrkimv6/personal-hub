# Monitor Page - Process Stop Script
# Stops FastAPI server, monitoring worker, and Frontend (including zombie processes)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Port settings
$ApiPort = 8000
$FrontendPort = 5173

# PID file paths
$PidDir = Join-Path $ProjectRoot ".pids"
$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"
$FrontendPidFile = Join-Path $PidDir "frontend.pid"

Write-Host "`n========================================" -ForegroundColor Red
Write-Host "  Monitor Page Process Stop" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# Stop process function
function Stop-MonitorProcess {
    param(
        [string]$Name,
        [string]$PidFile
    )

    $stopped = $false

    # Stop process from PID file
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($pid) {
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "[*] Stopping $Name (PID: $pid)..." -ForegroundColor Yellow

                # Try graceful termination
                $process | Stop-Process -ErrorAction SilentlyContinue

                # Wait a moment
                Start-Sleep -Seconds 2

                # Force kill if still running
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($process) {
                    Write-Host "[!] Force killing $Name..." -ForegroundColor Red
                    $process | Stop-Process -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 1
                }

                # Final check
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if (-not $process) {
                    Write-Host "[+] $Name stopped (PID: $pid)" -ForegroundColor Green
                    $stopped = $true
                } else {
                    Write-Host "[-] Failed to stop $Name (PID: $pid)" -ForegroundColor Red
                }
            } else {
                Write-Host "[*] $Name process already stopped (PID: $pid)" -ForegroundColor Gray
                $stopped = $true
            }
        }
        # Delete PID file
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "[*] $Name PID file not found" -ForegroundColor Gray
    }

    return $stopped
}

# Find and kill zombie processes
function Stop-ZombieProcesses {
    param([string]$Pattern, [string]$Name)

    $zombies = Get-WmiObject Win32_Process | Where-Object {
        $_.CommandLine -like "*$Pattern*" -and $_.Name -eq "python.exe"
    }

    if ($zombies) {
        Write-Host "`n[!] Found zombie processes for ${Name}:" -ForegroundColor Yellow
        foreach ($zombie in $zombies) {
            $cmdPreview = $zombie.CommandLine.Substring(0, [Math]::Min(80, $zombie.CommandLine.Length))
            Write-Host "    PID: $($zombie.ProcessId) - ${cmdPreview}..." -ForegroundColor Gray

            try {
                Stop-Process -Id $zombie.ProcessId -Force -ErrorAction Stop
                Write-Host "    [+] Killed" -ForegroundColor Green
            } catch {
                Write-Host "    [-] Failed to kill: $_" -ForegroundColor Red
            }
        }
    }
}

# Kill process using specific port
function Stop-ProcessOnPort {
    param(
        [int]$Port,
        [string]$Name
    )

    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            if ($procId -eq 0) { continue }
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "    [*] Killing process on port $Port ($Name): $($proc.Name) (PID: $procId)" -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
            }
        }
    }
}

# 1. Stop processes using PID files
Write-Host "[1] Stopping processes using PID files" -ForegroundColor Cyan
Write-Host "-" * 40

Stop-MonitorProcess -Name "API Server" -PidFile $ApiPidFile
Stop-MonitorProcess -Name "Worker" -PidFile $WorkerPidFile
Stop-MonitorProcess -Name "Frontend" -PidFile $FrontendPidFile

# 2. Stop processes by port
Write-Host "`n[2] Stopping processes by port" -ForegroundColor Cyan
Write-Host "-" * 40

Stop-ProcessOnPort -Port $ApiPort -Name "API Server"
Stop-ProcessOnPort -Port $FrontendPort -Name "Frontend"

# 3. Find and kill zombie processes
Write-Host "`n[3] Finding and killing zombie processes" -ForegroundColor Cyan
Write-Host "-" * 40

# API server related zombie processes
Stop-ZombieProcesses -Pattern "app.main" -Name "API Server"
Stop-ZombieProcesses -Pattern "uvicorn" -Name "Uvicorn"

# Worker related zombie processes
Stop-ZombieProcesses -Pattern "app.worker.monitor_worker" -Name "Worker"

# Frontend (vite/node) related zombie processes
Stop-ZombieProcesses -Pattern "vite" -Name "Frontend (Vite)"

# 4. Browser process cleanup (optional)
Write-Host "`n[4] Checking related browser processes" -ForegroundColor Cyan
Write-Host "-" * 40

$browserDataPath = Join-Path $ProjectRoot "browser_data"
$chromeProcesses = Get-WmiObject Win32_Process | Where-Object {
    $_.Name -eq "chrome.exe" -and $_.CommandLine -like "*$browserDataPath*"
}

if ($chromeProcesses) {
    Write-Host "[?] Found Chrome processes for monitoring." -ForegroundColor Yellow
    Write-Host "    Process count: $($chromeProcesses.Count)"

    $response = Read-Host "    Kill them? (y/N)"
    if ($response -eq "y" -or $response -eq "Y") {
        foreach ($chrome in $chromeProcesses) {
            try {
                Stop-Process -Id $chrome.ProcessId -Force -ErrorAction Stop
                Write-Host "    [+] Chrome killed (PID: $($chrome.ProcessId))" -ForegroundColor Green
            } catch {
                Write-Host "    [-] Failed to kill Chrome (PID: $($chrome.ProcessId))" -ForegroundColor Red
            }
        }
    }
} else {
    Write-Host "[*] No related Chrome processes found" -ForegroundColor Gray
}

# 5. Clean up browser profile lock file
$lockFile = Join-Path $browserDataPath "browser_profile\lockfile"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Write-Host "`n[+] Browser profile lock file deleted" -ForegroundColor Green
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  Process stop complete" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
