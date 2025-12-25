# Monitor Page - Windows Service Management Script
# Uses NSSM (Non-Sucking Service Manager) for service installation
#
# Usage:
#   .\service-install.ps1 -Action install       # Install production service
#   .\service-install.ps1 -Action install -IncludeDev  # Install both prod and dev services
#   .\service-install.ps1 -Action start -WithLogs      # Start service and open log window
#   .\service-install.ps1 -Action status        # Show service status
#   .\service-install.ps1 -Action stop          # Stop service
#   .\service-install.ps1 -Action restart -WithLogs    # Restart and open log window
#   .\service-install.ps1 -Action uninstall     # Uninstall service

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("install", "uninstall", "start", "stop", "restart", "status")]
    [string]$Action,

    [switch]$IncludeDev,   # Include development service (for install/uninstall)
    [switch]$WithLogs,     # Open log window after start/restart
    [switch]$Dev           # Target development service instead of production
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Service configuration
$ProdServiceName = "MonitorPage"
$DevServiceName = "MonitorPageDev"
$ProdDisplayName = "Monitor Page (Production)"
$DevDisplayName = "Monitor Page (Development)"

# Determine target service
if ($Dev) {
    $TargetServices = @($DevServiceName)
} elseif ($IncludeDev -and ($Action -eq "install" -or $Action -eq "uninstall")) {
    $TargetServices = @($ProdServiceName, $DevServiceName)
} else {
    $TargetServices = @($ProdServiceName)
}

# Check for NSSM
function Test-NssmInstalled {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    return $null -ne $nssm
}

# Check if running as administrator
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Get service configuration
function Get-ServiceConfig {
    param([string]$ServiceName)

    $isDev = $ServiceName -eq $DevServiceName

    return @{
        Name = $ServiceName
        DisplayName = if ($isDev) { $DevDisplayName } else { $ProdDisplayName }
        Description = if ($isDev) { "Monitor Page Development Server (API + Workers)" } else { "Monitor Page Production Server (API only, workers disabled)" }
        AppMode = if ($isDev) { "development" } else { "production" }
        ApiPort = if ($isDev) { 8001 } else { 8000 }
        LogDir = if ($isDev) { Join-Path $ProjectRoot "logs\dev" } else { Join-Path $ProjectRoot "logs" }
        StdoutLog = if ($isDev) { Join-Path $ProjectRoot "logs\dev\service_${ServiceName}.log" } else { Join-Path $ProjectRoot "logs\service_${ServiceName}.log" }
        StderrLog = if ($isDev) { Join-Path $ProjectRoot "logs\dev\service_${ServiceName}_err.log" } else { Join-Path $ProjectRoot "logs\service_${ServiceName}_err.log" }
    }
}

# Install service
function Install-MonitorService {
    param([string]$ServiceName)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Installing service: $($config.DisplayName)" -ForegroundColor Cyan

    # Create log directory if not exists
    if (-not (Test-Path $config.LogDir)) {
        New-Item -ItemType Directory -Path $config.LogDir -Force | Out-Null
    }

    # Find Python executable
    $pythonPath = $null
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $venvPython2 = Join-Path $ProjectRoot "venv\Scripts\python.exe"

    if (Test-Path $venvPython) {
        $pythonPath = $venvPython
    } elseif (Test-Path $venvPython2) {
        $pythonPath = $venvPython2
    } else {
        $pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    }

    if (-not $pythonPath) {
        Write-Host "[!] Python not found" -ForegroundColor Red
        return $false
    }

    Write-Host "    Python: $pythonPath" -ForegroundColor Gray

    # Install service with NSSM
    $arguments = "-m uvicorn app.main:app --host 0.0.0.0 --port $($config.ApiPort)"

    # Install
    nssm install $ServiceName $pythonPath $arguments

    # Set application directory
    nssm set $ServiceName AppDirectory $ProjectRoot

    # Set display name and description
    nssm set $ServiceName DisplayName $config.DisplayName
    nssm set $ServiceName Description $config.Description

    # Set environment variables
    $envVars = "APP_MODE=$($config.AppMode)", "PYTHONIOENCODING=utf-8"
    nssm set $ServiceName AppEnvironmentExtra $envVars

    # Set stdout/stderr log files
    nssm set $ServiceName AppStdout $config.StdoutLog
    nssm set $ServiceName AppStderr $config.StderrLog
    nssm set $ServiceName AppStdoutCreationDisposition 4  # Append
    nssm set $ServiceName AppStderrCreationDisposition 4  # Append

    # Set restart options
    nssm set $ServiceName AppRestartDelay 5000  # 5 seconds delay before restart
    nssm set $ServiceName AppThrottle 10000     # Minimum 10 seconds between restarts

    # Set startup type to Automatic
    nssm set $ServiceName Start SERVICE_AUTO_START

    Write-Host "[+] Service installed: $ServiceName" -ForegroundColor Green
    Write-Host "    Stdout: $($config.StdoutLog)" -ForegroundColor Gray
    Write-Host "    Stderr: $($config.StderrLog)" -ForegroundColor Gray

    return $true
}

# Uninstall service
function Uninstall-MonitorService {
    param([string]$ServiceName)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Uninstalling service: $($config.DisplayName)" -ForegroundColor Cyan

    # Stop service first if running
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Host "    [*] Stopping service..." -ForegroundColor Yellow
        nssm stop $ServiceName
        Start-Sleep -Seconds 2
    }

    # Remove service
    nssm remove $ServiceName confirm

    Write-Host "[+] Service uninstalled: $ServiceName" -ForegroundColor Green
    return $true
}

# Start service
function Start-MonitorService {
    param([string]$ServiceName, [switch]$OpenLogs)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Starting service: $($config.DisplayName)" -ForegroundColor Cyan

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $ServiceName" -ForegroundColor Red
        Write-Host "    Run: .\service-install.ps1 -Action install" -ForegroundColor Yellow
        return $false
    }

    if ($service.Status -eq "Running") {
        Write-Host "[!] Service already running" -ForegroundColor Yellow
    } else {
        nssm start $ServiceName
        Write-Host "[+] Service started: $ServiceName" -ForegroundColor Green
    }

    # Open logs if requested
    if ($OpenLogs) {
        Start-Sleep -Seconds 2
        Open-ServiceLogs -ServiceName $ServiceName
    }

    return $true
}

# Stop service
function Stop-MonitorService {
    param([string]$ServiceName)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Stopping service: $($config.DisplayName)" -ForegroundColor Cyan

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $ServiceName" -ForegroundColor Red
        return $false
    }

    if ($service.Status -eq "Stopped") {
        Write-Host "[!] Service already stopped" -ForegroundColor Yellow
    } else {
        nssm stop $ServiceName
        Write-Host "[+] Service stopped: $ServiceName" -ForegroundColor Green
    }

    return $true
}

# Restart service
function Restart-MonitorService {
    param([string]$ServiceName, [switch]$OpenLogs)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Restarting service: $($config.DisplayName)" -ForegroundColor Cyan

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $ServiceName" -ForegroundColor Red
        Write-Host "    Run: .\service-install.ps1 -Action install" -ForegroundColor Yellow
        return $false
    }

    nssm restart $ServiceName
    Write-Host "[+] Service restarted: $ServiceName" -ForegroundColor Green

    # Open logs if requested
    if ($OpenLogs) {
        Start-Sleep -Seconds 2
        Open-ServiceLogs -ServiceName $ServiceName
    }

    return $true
}

# Show service status
function Show-ServiceStatus {
    param([string]$ServiceName)

    $config = Get-ServiceConfig $ServiceName

    Write-Host ""
    Write-Host "[$($config.DisplayName)]" -ForegroundColor Cyan

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "  Status: NOT INSTALLED" -ForegroundColor Gray
        return
    }

    $statusColor = switch ($service.Status) {
        "Running" { "Green" }
        "Stopped" { "Red" }
        default { "Yellow" }
    }

    Write-Host "  Status: $($service.Status)" -ForegroundColor $statusColor
    Write-Host "  Port: $($config.ApiPort)" -ForegroundColor Gray
    Write-Host "  Mode: $($config.AppMode)" -ForegroundColor Gray

    # Check if log files exist
    if (Test-Path $config.StdoutLog) {
        $logSize = "{0:N2} KB" -f ((Get-Item $config.StdoutLog).Length / 1KB)
        Write-Host "  Log: $logSize" -ForegroundColor Gray
    }
}

# Open log windows
function Open-ServiceLogs {
    param([string]$ServiceName)

    $config = Get-ServiceConfig $ServiceName

    Write-Host "[*] Opening log windows..." -ForegroundColor Cyan

    $stdoutLog = $config.StdoutLog
    $stderrLog = $config.StderrLog

    # Check if Windows Terminal is available
    $wtPath = Get-Command wt -ErrorAction SilentlyContinue

    if ($wtPath) {
        # Windows Terminal - open split panes
        Write-Host "    Using Windows Terminal (split view)" -ForegroundColor Gray

        # Build command for split panes
        # Left: stdout, Right: stderr
        $wtArgs = @(
            "new-tab",
            "--title", "Service Logs: $ServiceName",
            "powershell", "-NoExit", "-Command", "Write-Host 'STDOUT Log' -ForegroundColor Cyan; Get-Content '$stdoutLog' -Wait -Tail 50 -Encoding UTF8",
            ";",
            "split-pane", "-H",
            "powershell", "-NoExit", "-Command", "Write-Host 'STDERR Log' -ForegroundColor Red; Get-Content '$stderrLog' -Wait -Tail 50 -Encoding UTF8"
        )

        Start-Process wt -ArgumentList $wtArgs

    } else {
        # Fallback to regular PowerShell window
        Write-Host "    Using PowerShell (Windows Terminal not available)" -ForegroundColor Gray

        # Open just stdout log in new window
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host 'Service Log: $ServiceName' -ForegroundColor Cyan; Get-Content '$stdoutLog' -Wait -Tail 50 -Encoding UTF8"
    }

    Write-Host "[+] Log window opened" -ForegroundColor Green
}

# Main execution
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Service Manager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
if ($Action -eq "install" -or $Action -eq "uninstall") {
    if (-not (Test-Administrator)) {
        Write-Host "[!] Administrator privileges required for install/uninstall" -ForegroundColor Red
        Write-Host "    Please run PowerShell as Administrator" -ForegroundColor Yellow
        exit 1
    }
}

if ($Action -ne "status" -and -not (Test-NssmInstalled)) {
    Write-Host "[!] NSSM not found" -ForegroundColor Red
    Write-Host "    Install with: winget install nssm" -ForegroundColor Yellow
    exit 1
}

# Execute action
switch ($Action) {
    "install" {
        foreach ($svc in $TargetServices) {
            Install-MonitorService -ServiceName $svc
            Write-Host ""
        }
        Write-Host "Installation complete." -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Yellow
        Write-Host "  .\service-install.ps1 -Action start         # Start service"
        Write-Host "  .\service-install.ps1 -Action start -WithLogs  # Start with log window"
    }
    "uninstall" {
        foreach ($svc in $TargetServices) {
            Uninstall-MonitorService -ServiceName $svc
            Write-Host ""
        }
    }
    "start" {
        foreach ($svc in $TargetServices) {
            Start-MonitorService -ServiceName $svc -OpenLogs:$WithLogs
        }
    }
    "stop" {
        foreach ($svc in $TargetServices) {
            Stop-MonitorService -ServiceName $svc
        }
    }
    "restart" {
        foreach ($svc in $TargetServices) {
            Restart-MonitorService -ServiceName $svc -OpenLogs:$WithLogs
        }
    }
    "status" {
        foreach ($svc in @($ProdServiceName, $DevServiceName)) {
            Show-ServiceStatus -ServiceName $svc
        }
        Write-Host ""
    }
}

Write-Host ""
