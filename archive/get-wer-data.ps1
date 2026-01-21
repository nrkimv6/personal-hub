# Get Windows Error Reporting Data
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== Windows Error Reporting - Kernel Dumps ===" -ForegroundColor Cyan

$werPath = "C:\ProgramData\Microsoft\Windows\WER\ReportArchive"
$werFiles = Get-ChildItem $werPath -Recurse -Filter "*.wer" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 5

foreach ($file in $werFiles) {
    Write-Host "`n--- $($file.LastWriteTime) - $($file.Directory.Name) ---" -ForegroundColor Yellow
    $content = Get-Content $file.FullName -ErrorAction SilentlyContinue

    # Extract key fields
    $content | Where-Object {
        $_ -match "^(EventType|BugCheckCode|BugCheckParameter|FailureBucket|FAILURE_ID|MODULE_NAME|IMAGE_NAME|FAULTING_MODULE|FAULTING_IP)"
    } | ForEach-Object { Write-Host $_ }
}

Write-Host "`n=== Checking for Mini Dumps ===" -ForegroundColor Cyan
$miniDumps = Get-ChildItem "C:\Windows\Minidump" -Filter "*.dmp" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending

if ($miniDumps) {
    $miniDumps | ForEach-Object {
        Write-Host "$($_.Name) - $($_.LastWriteTime) - $([math]::Round($_.Length/1KB,1)) KB"
    }
} else {
    Write-Host "No minidumps found"
}

Write-Host "`n=== Reliability History (Last 30 days) ===" -ForegroundColor Cyan
$reliability = Get-CimInstance -ClassName Win32_ReliabilityStabilityMetrics -ErrorAction SilentlyContinue |
    Where-Object { $_.TimeGenerated -gt (Get-Date).AddDays(-30) } |
    Sort-Object TimeGenerated -Descending |
    Select-Object -First 10

if ($reliability) {
    $reliability | ForEach-Object {
        Write-Host "$($_.TimeGenerated.ToString('yyyy-MM-dd')): Stability Index = $($_.SystemStabilityIndex)"
    }
}
