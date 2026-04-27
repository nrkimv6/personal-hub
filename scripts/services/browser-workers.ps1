# Browser Workers PowerShell wrapper
# Delegates to the current Python CLI entrypoint to avoid stale duplicated paths.
#
# Usage:
#   .\scripts\services\browser-workers.ps1 -Action start
#   .\scripts\services\browser-workers.ps1 -Action stop
#   .\scripts\services\browser-workers.ps1 -Action restart
#   .\scripts\services\browser-workers.ps1 -Action status
#   .\scripts\services\browser-workers.ps1 -Action restart-api
#   .\scripts\services\browser-workers.ps1 -Action restart-frontend
#   .\scripts\services\browser-workers.ps1 -Action restart-frontend -Public

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart", "status", "restart-api", "restart-frontend", "redis-status", "redis-restart", "redis-cleanup", "restart-listener", "restart-infra")]
    [string]$Action,

    [string]$Target,

    [switch]$Public
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$BrowserWorkersPy = Join-Path $ScriptDir "browser_workers.py"

if (-not (Test-Path $BrowserWorkersPy)) {
    Write-Error "browser_workers.py를 찾지 못했습니다: $BrowserWorkersPy"
    exit 1
}

$PythonCandidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot "venv\Scripts\python.exe")
)
$PythonExe = $PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $PythonExe) {
    Write-Error "python.exe를 찾지 못했습니다. 확인한 경로: $($PythonCandidates -join ', ')"
    exit 1
}

$Arguments = @($BrowserWorkersPy, $Action)
if ($Action -eq "restart-infra" -and $Target) {
    $Arguments += $Target
}
if ($Public) {
    $Arguments += "--public"
}

& $PythonExe @Arguments
$exitCode = $LASTEXITCODE

if ($Action -eq "restart-frontend" -and $exitCode -ne 0) {
    Write-Host "restart-frontend failed. Review the emitted listener/build_log/class diagnostics above." -ForegroundColor Yellow
    Write-Host "If the output mentions Access denied, EPERM, or another session owning the listener, treat it as a permission or service-lock issue." -ForegroundColor Yellow
}

exit $exitCode
