# Chrome process cleanup script
Write-Host "Starting Chrome cleanup..."

# Kill Playwright Chromium processes (identified by ms-playwright path)
$chromiumProcesses = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {
    try {
        $path = $_.Path
        $path -like "*ms-playwright*"
    } catch {
        $false
    }
}

if ($chromiumProcesses) {
    Write-Host "Found $($chromiumProcesses.Count) Playwright Chromium processes"
    $chromiumProcesses | Stop-Process -Force
    Write-Host "Playwright Chromium processes killed"
} else {
    Write-Host "No Playwright Chromium processes found"
}

# Check and delete profile LOCK files
$lockFiles = Get-ChildItem -Path "D:\work\project\tools\monitor-page\data\browser_profiles" -Recurse -Filter "LOCK" -File -ErrorAction SilentlyContinue

if ($lockFiles) {
    Write-Host ""
    Write-Host "Found LOCK files:"
    foreach ($lock in $lockFiles) {
        Write-Host "  - $($lock.FullName)"
        try {
            Remove-Item $lock.FullName -Force -ErrorAction Stop
            Write-Host "    Deleted"
        } catch {
            Write-Host "    Failed to delete (in use): $_"
        }
    }
} else {
    Write-Host ""
    Write-Host "No residual LOCK files found"
}

# Check remaining Chrome processes
$remaining = (Get-Process chrome -ErrorAction SilentlyContinue).Count
Write-Host ""
Write-Host "Cleanup complete. Remaining Chrome processes: $remaining"
