param(
    [ValidateSet("status", "enable", "disable")]
    [string]$Action = "disable",
    [string]$ProjectRootOverride,
    [switch]$NoRestartApi
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = if ($ProjectRootOverride) {
    $ProjectRootOverride
} else {
    Split-Path -Parent (Split-Path -Parent $ScriptDir)
}
$EnvPath = Join-Path $ProjectRoot ".env"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BrowserWorkers = Join-Path $ProjectRoot "scripts\services\browser_workers.py"
$SettingName = "MEGABEAUTY_KAKAO_ALERT_ENABLED"

function Get-EnvLines {
    if (Test-Path $EnvPath) {
        return @(Get-Content $EnvPath)
    }

    return @()
}

function Get-SettingValue {
    if (-not (Test-Path $EnvPath)) {
        return $null
    }

    foreach ($line in Get-Content $EnvPath) {
        if ($line -match "^\s*$SettingName\s*=\s*(.+?)\s*$") {
            return $Matches[1].Trim()
        }
    }

    return $null
}

function Set-SettingValue([string]$Value) {
    $lines = Get-EnvLines
    $updated = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$SettingName\s*=") {
            $lines[$i] = "$SettingName=$Value"
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        if ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -ne "") {
            $lines += ""
        }
        $lines += "# 메가뷰티쇼 카카오 알림"
        $lines += "$SettingName=$Value"
    }

    Set-Content -Path $EnvPath -Value $lines -Encoding utf8
}

function Restart-AdminApi {
    if (-not (Test-Path $PythonExe)) {
        throw "Python executable not found: $PythonExe"
    }
    if (-not (Test-Path $BrowserWorkers)) {
        throw "browser_workers.py not found: $BrowserWorkers"
    }

    Push-Location $ProjectRoot
    try {
        & $PythonExe $BrowserWorkers restart-api
        if ($LASTEXITCODE -ne 0) {
            throw "restart-api failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

$previousValue = Get-SettingValue
$previousLabel = if ($null -eq $previousValue -or $previousValue -eq "") { "<unset>" } else { $previousValue }

if ($Action -eq "status") {
    $effectiveValue = if ($null -eq $previousValue -or $previousValue -eq "") { "false (default)" } else { $previousValue }
Write-Host "[$SettingName] current = $effectiveValue"
    exit 0
}

$targetValue = if ($Action -eq "enable") { "true" } else { "false" }
Set-SettingValue -Value $targetValue

Write-Host "[$SettingName] $previousLabel -> $targetValue"

if ($NoRestartApi) {
    Write-Host "API restart skipped (--NoRestartApi)."
    exit 0
}

Write-Host "Restarting admin API to apply .env change..."
Restart-AdminApi
Write-Host "Admin API restart completed."
