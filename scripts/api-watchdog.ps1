# API Watchdog Script
# External health checker for API server with staged recovery
#
# Runs independently of API server to detect hangs that internal health monitor cannot detect
# (When API hangs, its internal HealthMonitorService also hangs)
#
# Recovery stages:
#   Stage 1 (3 failures): Self-restart API (graceful) → NSSM restart fallback
#   Stage 2 (6 failures): Force kill port owner + NSSM restart
#   Stage 3 (9 failures): System reboot (last resort)
#
# Usage:
#   .\scripts\api-watchdog.ps1 -Dev           # Monitor development API (port 8001)
#   .\scripts\api-watchdog.ps1                # Monitor production API (port 8000)
#   .\scripts\api-watchdog.ps1 -Dev -Verbose  # With verbose output
#
# See: docs/2026-01-04-api-stability-improvements.md

param(
    [switch]$Dev,
    [int]$CheckInterval = 30,
    [int]$Timeout = 10,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Load Telegram alert function
. (Join-Path $ScriptDir "Send-TelegramAlert.ps1")

# Configuration
$port = if ($Dev) { 8001 } else { 8000 }
$serviceName = if ($Dev) { "Monitor Page (Development)" } else { "Monitor Page (Production)" }
$mode = if ($Dev) { "Development" } else { "Production" }
$healthEndpoint = "http://localhost:$port/api/v1/system/status"

# State tracking
$failureCount = 0
$lastSuccessTime = Get-Date
$totalRestarts = 0

function Write-WatchdogLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "INFO"  { "Cyan" }
        "OK"    { "Green" }
        "DEBUG" { "DarkGray" }
        default { "White" }
    }

    if ($Level -eq "DEBUG" -and -not $Verbose) {
        return
    }

    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Test-ApiHealth {
    try {
        $response = Invoke-WebRequest $healthEndpoint -TimeoutSec $Timeout -UseBasicParsing
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Restart-ApiService {
    param([string]$Reason)

    Write-WatchdogLog "Attempting API restart: $Reason" "WARN"

    # 1순위: Self-Restart API (graceful, 관리자 권한 불필요, 포트 정상 해제)
    $selfRestartEndpoint = "http://localhost:${port}/api/v1/system/self-restart?delay=2"
    try {
        $response = Invoke-WebRequest -Uri $selfRestartEndpoint -Method POST -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-WatchdogLog "Self-restart API called (graceful shutdown → NSSM auto-restart)" "OK"
            return $true
        }
    } catch {
        Write-WatchdogLog "Self-restart API unavailable: $($_.Exception.Message)" "WARN"
    }

    # 2순위: NSSM restart (관리자 권한 필요)
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        try {
            Write-WatchdogLog "Falling back to NSSM restart (admin mode)" "WARN"
            $result = nssm restart $serviceName 2>&1
            Write-WatchdogLog "NSSM restart command executed" "INFO"
            return $true
        } catch {
            Write-WatchdogLog "NSSM restart failed: $_" "ERROR"
            return $false
        }
    }

    # 3순위: Stop-Process -Force (포트 점유 위험 있음 — 최후의 수단)
    Write-WatchdogLog "Non-admin mode: Falling back to Stop-Process -Force (port issue risk)" "WARN"
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
    if ($conn) {
        try {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
            Write-WatchdogLog "Force killed PID $($conn.OwningProcess) on port $port. NSSM will auto-restart." "WARN"
            return $true
        } catch {
            Write-WatchdogLog "Failed to kill process: $_" "ERROR"
            return $false
        }
    } else {
        Write-WatchdogLog "No process found on port $port" "WARN"
        return $false
    }
}

function Force-KillPortOwner {
    Write-WatchdogLog "Force killing port $port owner (zombie process handling)" "WARN"

    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($c in $conn) {
            try {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                Write-WatchdogLog "Force killed PID: $($c.OwningProcess)" "INFO"
            } catch {
                Write-WatchdogLog "Failed to kill PID $($c.OwningProcess): $_" "WARN"
            }
        }
        return $true
    } else {
        Write-WatchdogLog "No process holding port $port" "INFO"
        return $false
    }
}

function Request-SystemReboot {
    param([string]$Reason)

    Write-WatchdogLog "CRITICAL: Requesting system reboot - $Reason" "ERROR"

    # Send alert before reboot
    Send-TelegramAlert "🔴 <b>시스템 재부팅</b>`n`n이유: $Reason`n환경: $mode`n시간: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    # Give time for alert to send
    Start-Sleep -Seconds 3

    # Initiate reboot
    shutdown /r /t 10 /c "Monitor Page API 서버 복구 불가로 인한 자동 재부팅"
}

# Main watchdog loop
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  API Watchdog Started" -ForegroundColor Cyan
Write-Host "  Mode: $mode (port $port)" -ForegroundColor Gray
Write-Host "  Check Interval: ${CheckInterval}s" -ForegroundColor Gray
Write-Host "  Health Endpoint: $healthEndpoint" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-WatchdogLog "Watchdog started for $mode API" "OK"

# Initial health check
if (Test-ApiHealth) {
    Write-WatchdogLog "Initial health check passed" "OK"
} else {
    Write-WatchdogLog "Initial health check failed - API may be starting up" "WARN"
}

while ($true) {
    $isHealthy = Test-ApiHealth

    if ($isHealthy) {
        if ($failureCount -gt 0) {
            Write-WatchdogLog "API recovered after $failureCount failures" "OK"
            Send-TelegramAlert "✅ <b>API 복구됨</b>`n`n환경: $mode`n실패 횟수: $failureCount`n다운타임: $([int]((Get-Date) - $lastSuccessTime).TotalSeconds)초"
        }
        $failureCount = 0
        $lastSuccessTime = Get-Date
        Write-WatchdogLog "Health check passed" "DEBUG"
    } else {
        $failureCount++
        $downtime = [int]((Get-Date) - $lastSuccessTime).TotalSeconds
        Write-WatchdogLog "Health check FAILED ($failureCount/9) - Downtime: ${downtime}s" "WARN"

        # Staged recovery
        switch ($failureCount) {
            3 {
                # Stage 1: NSSM restart
                Send-TelegramAlert "⚠️ <b>API Hang 감지</b>`n`n환경: $mode`n포트: $port`n실패: $failureCount회 연속`n조치: 프로세스 재시작 시도"

                if (Restart-ApiService "Stage 1: 3 consecutive failures") {
                    $totalRestarts++
                }
                Start-Sleep -Seconds 10  # Wait for restart
            }
            6 {
                # Stage 2: Force kill + NSSM restart
                Send-TelegramAlert "🟠 <b>API 복구 실패</b>`n`n환경: $mode`n포트: $port`n실패: $failureCount회 연속`n조치: 포트 강제 해제 시도"

                Force-KillPortOwner
                Start-Sleep -Seconds 5

                if (Restart-ApiService "Stage 2: Port force release") {
                    $totalRestarts++
                }
                Start-Sleep -Seconds 10
            }
            { $_ -ge 9 } {
                # Stage 3: System reboot (last resort)
                Request-SystemReboot "API 복구 불가 (9회 연속 실패, $totalRestarts회 재시작 시도 후)"

                # Reset counter (shouldn't reach here if reboot works)
                $failureCount = 0
                Start-Sleep -Seconds 60
            }
        }
    }

    Start-Sleep -Seconds $CheckInterval
}
