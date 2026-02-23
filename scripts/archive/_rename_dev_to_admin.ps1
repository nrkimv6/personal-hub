# Check what has logs\dev open using handle
$src = "D:\work\project\tools\monitor-page\logs\dev"
$dst = "D:\work\project\tools\monitor-page\logs\admin"

# Try to find what's locking
$locked = $false
try {
    $testFile = Join-Path $src "_lock_test.tmp"
    [System.IO.File]::Open($testFile, 'Create', 'ReadWrite', 'None') | Out-Null
    Remove-Item $testFile -Force
} catch {
    $locked = $true
    Write-Host "Directory may be locked: $($_.Exception.Message)"
}

# Try rename anyway
try {
    Rename-Item -Path $src -NewName "admin" -ErrorAction Stop
    Write-Host "Renamed logs\dev -> logs\admin OK"
} catch {
    Write-Host "Rename failed: $($_.Exception.Message)"

    # Alternative: create admin dir and try to move files
    Write-Host "Trying alternative: create admin dir"
    if (-not (Test-Path $dst)) {
        New-Item -ItemType Directory -Path $dst | Out-Null
    }
    Write-Host "Created $dst"
    Write-Host "NOTE: logs\dev rename requires manual intervention - directory is locked by a running process"
}
