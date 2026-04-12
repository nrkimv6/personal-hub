# Port Utilities Module
# Provides functions for port status checking including zombie port detection
#
# Usage:
#   . "$ScriptDir\port-utils.ps1"
#   $result = Test-ZombiePort -Port 8001
#   if ($result.IsZombie) { Write-Host $result.Message }

function Test-ZombiePort {
    <#
    .SYNOPSIS
        Detects zombie ports - ports held by non-existent processes

    .DESCRIPTION
        Checks if a port is in LISTENING state and verifies if the owning process exists.
        A zombie port occurs when a process terminates abnormally but the OS still holds the port.

    .PARAMETER Port
        The port number to check

    .OUTPUTS
        $null if port is not in use
        Hashtable with keys: Port, PID, IsZombie, Message (if zombie), ProcessName (if not zombie)

    .EXAMPLE
        $result = Test-ZombiePort -Port 8001
        if ($result -and $result.IsZombie) {
            Write-Host "Zombie detected: $($result.Message)"
        }
    #>
    param(
        [Parameter(Mandatory=$true)]
        [int]$Port
    )

    # netstat 기반으로 조회 (Session 0에서 Get-NetTCPConnection 행 방지)
    $owningPid = $null
    try {
        $lines = netstat -ano 2>$null | Select-String ":${Port}\s+.*LISTENING"
        if ($lines) {
            $firstLine = $lines | Select-Object -First 1
            if ($firstLine -match '\s(\d+)\s*$') {
                $owningPid = [int]$Matches[1]
            }
        }
    } catch { }

    if (-not $owningPid -or $owningPid -eq 0) {
        return $null
    }
    $process = Get-Process -Id $owningPid -ErrorAction SilentlyContinue

    if (-not $process) {
        return @{
            Port = $Port
            PID = $owningPid
            IsZombie = $true
            Message = "Port ${Port}: Zombie PID $owningPid detected. Reboot required or try: net stop winnat && net start winnat"
        }
    }

    return @{
        Port = $Port
        PID = $owningPid
        IsZombie = $false
        ProcessName = $process.ProcessName
    }
}

function Test-PortsBeforeStart {
    <#
    .SYNOPSIS
        Checks multiple ports for zombie status before starting services

    .PARAMETER Ports
        Array of port numbers to check

    .PARAMETER ServiceName
        Name of the service for logging purposes

    .OUTPUTS
        $true if all ports are available or in normal use
        $false if zombie port detected (blocks startup)
    #>
    param(
        [Parameter(Mandatory=$true)]
        [int[]]$Ports,

        [string]$ServiceName = "Service"
    )

    $hasZombie = $false

    foreach ($port in $Ports) {
        $result = Test-ZombiePort -Port $port

        if ($result) {
            if ($result.IsZombie) {
                Write-Host ""
                Write-Host "========================================" -ForegroundColor Red
                Write-Host "  ZOMBIE PORT DETECTED!" -ForegroundColor Red
                Write-Host "========================================" -ForegroundColor Red
                Write-Host ""
                Write-Host "Port $port is held by PID $($result.PID) which no longer exists." -ForegroundColor Yellow
                Write-Host ""
                Write-Host "Solutions:" -ForegroundColor Cyan
                Write-Host "  1. Restart WinNAT (run as admin):" -ForegroundColor White
                Write-Host "     net stop winnat && net start winnat" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  2. If that doesn't work, reboot the system" -ForegroundColor White
                Write-Host ""
                $hasZombie = $true
            } else {
                Write-Host "[INFO] Port $port in use by $($result.ProcessName) (PID: $($result.PID))" -ForegroundColor Gray
            }
        }
    }

    if ($hasZombie) {
        Write-Host "Cannot start $ServiceName due to zombie port(s)." -ForegroundColor Red
        Write-Host ""
        return $false
    }

    return $true
}
