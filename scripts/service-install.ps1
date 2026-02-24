# Monitor Page - Windows Service Management Script
# Uses NSSM (Non-Sucking Service Manager) for service installation
#
# Usage:
#   .\service-install.ps1 -Action install           # Install production service
#   .\service-install.ps1 -Action install -IncludeAdmin  # Install prod + admin services
#   .\service-install.ps1 -Action start -WithLogs   # Start service and open log window
#   .\service-install.ps1 -Action status            # Show service status
#   .\service-install.ps1 -Action stop              # Stop service
#   .\service-install.ps1 -Action restart -WithLogs # Restart and open log window
#   .\service-install.ps1 -Action uninstall         # Uninstall service

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("install", "uninstall", "start", "stop", "restart", "status")]
    [string]$Action,

    [switch]$IncludeAdmin,  # Include admin service (for install/uninstall)
    [switch]$WithLogs,     # Open log window after start/restart
    [switch]$Admin,        # Target admin service instead of production
    [string]$ServiceUser,  # Service account username (e.g., ".\Narang")
    [string]$ServicePass   # Service account password
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Import port utilities
. "$ScriptDir\port-utils.ps1"

# Service configuration
# Python service runner: service_run.py (service-run.ps1에서 마이그레이션됨)
# See: docs/plan/2026-02-18_service-runner-python-migration.md
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
}
$ServiceScript = Join-Path $ScriptDir "service_run.py"

$services = @(
    @{
        Name = "MonitorPage-Public"
        DisplayName = "Monitor Page (Public)"
        Description = "Monitor Page Public Server - API(8000) + Frontend(6100)"
        Application = $VenvPython
        AppArgs = "`"$ServiceScript`""
        LogDir = Join-Path $ProjectRoot "logs"
    }
)

if ($IncludeAdmin -and ($Action -eq "install" -or $Action -eq "uninstall")) {
    $services += @{
        Name = "MonitorPage-Admin"
        DisplayName = "Monitor Page (Admin)"
        Description = "Monitor Page Admin Server - API(8001) + Frontend(6101) + Workers"
        Application = $VenvPython
        AppArgs = "`"$ServiceScript`" --admin"
        LogDir = Join-Path $ProjectRoot "logs\admin"
    }
}

# Determine target services for start/stop/restart
if ($Admin -and ($Action -in @("start", "stop", "restart"))) {
    $targetServices = @(
        @{
            Name = "MonitorPage-Admin"
            DisplayName = "Monitor Page (Admin)"
            Description = "Monitor Page Admin Server - API(8001) + Frontend(6101) + Workers"
            Application = $VenvPython
            AppArgs = "`"$ServiceScript`" --admin"
            LogDir = Join-Path $ProjectRoot "logs\admin"
        }
    )
} else {
    $targetServices = $services
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

# Install service
function Install-MonitorService {
    param($svc)

    Write-Host "[*] Installing service: $($svc.Name)" -ForegroundColor Cyan

    # Create log directory if not exists
    if (-not (Test-Path $svc.LogDir)) {
        New-Item -ItemType Directory -Path $svc.LogDir -Force | Out-Null
    }

    # Remove existing service if exists
    $existing = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "    Removing existing service..." -ForegroundColor Yellow
        $null = nssm stop $svc.Name confirm 2>&1
        $null = nssm remove $svc.Name confirm 2>&1
    }

    # Install service - Python service runner
    nssm install $svc.Name $svc.Application
    nssm set $svc.Name AppParameters $svc.AppArgs
    nssm set $svc.Name AppDirectory $ProjectRoot

    # Set display name and description
    nssm set $svc.Name DisplayName $svc.DisplayName
    nssm set $svc.Name Description $svc.Description

    # Set startup type to Delayed Auto Start (start after boot completes)
    nssm set $svc.Name Start SERVICE_DELAYED_AUTO_START

    # Set log files
    $stdoutLog = Join-Path $svc.LogDir "service_$($svc.Name).log"
    $stderrLog = Join-Path $svc.LogDir "service_$($svc.Name)_err.log"
    nssm set $svc.Name AppStdout $stdoutLog
    nssm set $svc.Name AppStderr $stderrLog
    nssm set $svc.Name AppStdoutCreationDisposition 4  # Append
    nssm set $svc.Name AppStderrCreationDisposition 4  # Append

    # Log rotation (10MB)
    nssm set $svc.Name AppRotateFiles 1
    nssm set $svc.Name AppRotateBytes 10485760

    # Set restart throttle (10 seconds delay between restarts)
    # Prevents port conflict when service restarts too quickly
    nssm set $svc.Name AppThrottle 10000

    # Set Playwright browsers path to project-local directory
    # This allows SYSTEM account to find browsers (user AppData is not accessible)
    $PlaywrightBrowsersPath = Join-Path $ProjectRoot ".playwright"
    if (-not (Test-Path $PlaywrightBrowsersPath)) {
        Write-Host "    [!] Playwright browsers not found at: $PlaywrightBrowsersPath" -ForegroundColor Yellow
        Write-Host "    Run: `$env:PLAYWRIGHT_BROWSERS_PATH='$PlaywrightBrowsersPath'; playwright install chromium" -ForegroundColor Yellow
    }
    nssm set $svc.Name AppEnvironmentExtra "PLAYWRIGHT_BROWSERS_PATH=$PlaywrightBrowsersPath"
    Write-Host "    Playwright: $PlaywrightBrowsersPath" -ForegroundColor Gray

    # Set service account if provided
    if ($ServiceUser -and $ServicePass) {
        nssm set $svc.Name ObjectName $ServiceUser $ServicePass
        Write-Host "    Account: $ServiceUser" -ForegroundColor Gray
    }

    Write-Host "[+] Service installed: $($svc.Name)" -ForegroundColor Green
    Write-Host "    Stdout: $stdoutLog" -ForegroundColor Gray
    Write-Host "    Stderr: $stderrLog" -ForegroundColor Gray

    return $true
}

# Uninstall service
function Uninstall-MonitorService {
    param($svc)

    Write-Host "[*] Uninstalling service: $($svc.Name)" -ForegroundColor Cyan

    # Stop service first if running
    $service = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Host "    [*] Stopping service..." -ForegroundColor Yellow
        nssm stop $svc.Name
        Start-Sleep -Seconds 2
    }

    # Remove service
    nssm remove $svc.Name confirm

    Write-Host "[+] Service uninstalled: $($svc.Name)" -ForegroundColor Green
    return $true
}

# Start service
function Start-MonitorService {
    param($svc, [switch]$OpenLogs)

    Write-Host "[*] Starting service: $($svc.DisplayName)" -ForegroundColor Cyan

    # Determine ports based on service type
    $portsToCheck = if ($svc.Name -eq "MonitorPage-Admin") {
        @(8001, 5174)  # Dev API + Frontend
    } else {
        @(8000, 5173)  # Prod API + Frontend
    }

    # Check for zombie ports before starting
    if (-not (Test-PortsBeforeStart -Ports $portsToCheck -ServiceName $svc.DisplayName)) {
        return $false
    }

    $service = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $($svc.Name)" -ForegroundColor Red
        Write-Host "    Run: .\service-install.ps1 -Action install" -ForegroundColor Yellow
        return $false
    }

    if ($service.Status -eq "Running") {
        Write-Host "[!] Service already running" -ForegroundColor Yellow
    } else {
        nssm start $svc.Name
        Write-Host "[+] Service started: $($svc.Name)" -ForegroundColor Green
    }

    # Open logs if requested
    if ($OpenLogs) {
        Start-Sleep -Seconds 2
        Open-ServiceLogs -svc $svc
    }

    return $true
}

# Stop service
function Stop-MonitorService {
    param($svc)

    Write-Host "[*] Stopping service: $($svc.DisplayName)" -ForegroundColor Cyan

    $service = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $($svc.Name)" -ForegroundColor Red
        return $false
    }

    if ($service.Status -eq "Stopped") {
        Write-Host "[!] Service already stopped" -ForegroundColor Yellow
    } else {
        nssm stop $svc.Name
        Write-Host "[+] Service stopped: $($svc.Name)" -ForegroundColor Green
    }

    return $true
}

# Restart service
function Restart-MonitorService {
    param($svc, [switch]$OpenLogs)

    Write-Host "[*] Restarting service: $($svc.DisplayName)" -ForegroundColor Cyan

    $service = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Host "[!] Service not found: $($svc.Name)" -ForegroundColor Red
        Write-Host "    Run: .\service-install.ps1 -Action install" -ForegroundColor Yellow
        return $false
    }

    nssm restart $svc.Name
    Write-Host "[+] Service restarted: $($svc.Name)" -ForegroundColor Green

    # Open logs if requested
    if ($OpenLogs) {
        Start-Sleep -Seconds 2
        Open-ServiceLogs -svc $svc
    }

    return $true
}

# Show service status
function Show-ServiceStatus {
    param($svc)

    Write-Host ""
    Write-Host "[$($svc.DisplayName)]" -ForegroundColor Cyan

    $service = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
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

    # Check if log files exist
    $stdoutLog = Join-Path $svc.LogDir "service_$($svc.Name).log"
    if (Test-Path $stdoutLog) {
        $logSize = "{0:N2} KB" -f ((Get-Item $stdoutLog).Length / 1KB)
        Write-Host "  Log: $logSize" -ForegroundColor Gray
    }
}

# Open log windows - uses logs.ps1 for unified log view
function Open-ServiceLogs {
    param($svc)

    Write-Host "[*] Opening unified log window..." -ForegroundColor Cyan

    # Determine if this is Admin service
    $isAdmin = $svc.Args -like "*-Admin*"
    $modeLabel = if ($isAdmin) { "ADMIN" } else { "PUBLIC" }
    $logsScript = Join-Path $ScriptDir "logs.ps1"

    # Build command string for wt (needs proper quoting)
    $adminFlag = if ($isAdmin) { " -Admin" } else { "" }
    $psCmd = "& '$logsScript' -Follow$adminFlag"

    # Check if Windows Terminal is available
    $wtPath = Get-Command wt -ErrorAction SilentlyContinue

    if ($wtPath) {
        # Windows Terminal - use cmd /c to properly pass the command
        Write-Host "    Using Windows Terminal" -ForegroundColor Gray
        Start-Process cmd -ArgumentList "/c", "wt", "new-tab", "--title", "`"[$modeLabel] Logs`"", "powershell", "-NoExit", "-Command", "`"$psCmd`""
    } else {
        # Fallback to regular PowerShell window
        Write-Host "    Using PowerShell" -ForegroundColor Gray
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $psCmd
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
        foreach ($svc in $services) {
            Install-MonitorService $svc
            Write-Host ""
        }
        Write-Host "Installation complete." -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Yellow
        Write-Host "  .\service-install.ps1 -Action start         # Start service"
        Write-Host "  .\service-install.ps1 -Action start -WithLogs  # Start with log window"
    }
    "uninstall" {
        foreach ($svc in $services) {
            Uninstall-MonitorService $svc
            Write-Host ""
        }
    }
    "start" {
        foreach ($svc in $targetServices) {
            Start-MonitorService $svc -OpenLogs:$WithLogs
        }
    }
    "stop" {
        foreach ($svc in $targetServices) {
            Stop-MonitorService $svc
        }
    }
    "restart" {
        foreach ($svc in $targetServices) {
            Restart-MonitorService $svc -OpenLogs:$WithLogs
        }
    }
    "status" {
        # Always show both services for status
        $allServices = @(
            @{
                Name = "MonitorPage-Public"
                DisplayName = "Monitor Page (Public)"
                LogDir = Join-Path $ProjectRoot "logs"
            },
            @{
                Name = "MonitorPage-Admin"
                DisplayName = "Monitor Page (Admin)"
                LogDir = Join-Path $ProjectRoot "logs\admin"
            }
        )
        foreach ($svc in $allServices) {
            Show-ServiceStatus $svc
        }
        Write-Host ""
    }
}

Write-Host ""
