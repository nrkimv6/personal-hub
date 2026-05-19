function Get-LatestFrontendErrorLog {
    param([string]$LogDir)

    if (-not $LogDir -or -not (Test-Path -LiteralPath $LogDir)) {
        return $null
    }

    Get-ChildItem -LiteralPath $LogDir -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like "frontend_err_*.log" -or
            ($_.Name -like "frontend_*.log" -and $_.Name -notlike "frontend_watchdog_*.log")
        } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
}

function Test-FrontendEnoentCrashLog {
    param([string]$LogPath)

    if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath)) {
        return $false
    }

    try {
        $content = Get-Content -LiteralPath $LogPath -Raw -ErrorAction Stop
    } catch {
        return $false
    }

    return ($content -match "ENOENT" -and
        $content -match "createProxy" -and
        $content -match "@sveltejs[/\\]kit[/\\]src[/\\]core[/\\]sync[/\\]write_types")
}

function Test-ShouldShortBackoff {
    param([string]$LogDir)

    $latest = Get-LatestFrontendErrorLog -LogDir $LogDir
    if (-not $latest) {
        return $false
    }

    Test-FrontendEnoentCrashLog -LogPath $latest.FullName
}

function Get-FrontendBackoffPauseMinutes {
    param([int]$StandardPauseMinutes)

    $shortPause = 10
    if ($env:FRONTEND_WATCHDOG_ENOENT_PAUSE_MINUTES) {
        try {
            $shortPause = [int]$env:FRONTEND_WATCHDOG_ENOENT_PAUSE_MINUTES
        } catch {
            $shortPause = 10
        }
    }

    if ($shortPause -gt 0) {
        return $shortPause
    }

    return $StandardPauseMinutes
}
