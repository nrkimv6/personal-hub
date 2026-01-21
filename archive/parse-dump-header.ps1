# Parse MEMORY.DMP Header
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$dumpPath = "C:\WINDOWS\MEMORY.DMP"

if (-not (Test-Path $dumpPath)) {
    Write-Host "MEMORY.DMP not found" -ForegroundColor Red
    exit
}

Write-Host "=== MEMORY.DMP Analysis ===" -ForegroundColor Cyan
$file = Get-Item $dumpPath
Write-Host "File: $($file.FullName)"
Write-Host "Size: $([math]::Round($file.Length/1GB,2)) GB"
Write-Host "Date: $($file.LastWriteTime)"

# Read dump header (first 4KB)
Write-Host "`n=== Dump Header (Raw) ===" -ForegroundColor Cyan
try {
    $fs = [System.IO.File]::OpenRead($dumpPath)
    $buffer = New-Object byte[] 4096
    $fs.Read($buffer, 0, 4096) | Out-Null
    $fs.Close()

    # Check dump signature
    $signature = [System.Text.Encoding]::ASCII.GetString($buffer, 0, 8)
    Write-Host "Signature: $signature"

    # Dump type at offset 0x00
    if ($signature -eq "PAGEDUMP" -or $signature -eq "PAGEDU64") {
        Write-Host "Dump Type: Full Memory Dump (64-bit)"
    }

    # BugCheck code is typically at offset 0x1000 for MEMORY.DMP
    # Try to read from WER data instead
} catch {
    Write-Host "Error reading dump: $_" -ForegroundColor Red
}

Write-Host "`n=== Alternative: Using WMI Win32_NTLogEvent ===" -ForegroundColor Cyan
$events = Get-WmiObject -Query "SELECT * FROM Win32_NTLogEvent WHERE LogFile='System' AND EventCode='1001' AND SourceName='Microsoft-Windows-WER-SystemErrorReporting'" -ErrorAction SilentlyContinue |
    Sort-Object TimeWritten -Descending |
    Select-Object -First 3

foreach ($evt in $events) {
    Write-Host "`n--- $($evt.TimeWritten) ---" -ForegroundColor Yellow
    Write-Host $evt.Message
}
