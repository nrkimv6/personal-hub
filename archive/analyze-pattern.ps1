# BSOD Pattern Analysis
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== BSOD Pattern Analysis ===" -ForegroundColor Cyan

$events = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; StartTime=(Get-Date).AddDays(-60)} -ErrorAction SilentlyContinue

Write-Host "`nTotal BSOD count: $($events.Count)" -ForegroundColor Yellow

Write-Host "`n--- By Hour of Day ---" -ForegroundColor Cyan
$events | Group-Object { $_.TimeCreated.Hour } | Sort-Object Name | ForEach-Object {
    Write-Host "  $($_.Name.PadLeft(2,'0')):00 - $($_.Count) times"
}

Write-Host "`n--- By Day of Week ---" -ForegroundColor Cyan
$events | Group-Object { $_.TimeCreated.DayOfWeek } | ForEach-Object {
    Write-Host "  $($_.Name): $($_.Count) times"
}

Write-Host "`n--- By Error Code ---" -ForegroundColor Cyan
$events | ForEach-Object {
    if ($_.Message -match '0x[0-9a-fA-F]{8}') {
        $matches[0]
    }
} | Group-Object | Sort-Object Count -Descending | ForEach-Object {
    $codeName = switch ($_.Name) {
        '0x0000000a' { 'IRQL_NOT_LESS_OR_EQUAL' }
        '0x00000139' { 'KERNEL_SECURITY_CHECK_FAILURE' }
        '0x00000133' { 'DPC_WATCHDOG_VIOLATION' }
        '0x0000001e' { 'KMODE_EXCEPTION_NOT_HANDLED' }
        '0x0000003b' { 'SYSTEM_SERVICE_EXCEPTION' }
        '0x000000d1' { 'DRIVER_IRQL_NOT_LESS_OR_EQUAL' }
        default { 'Unknown' }
    }
    Write-Host "  $($_.Name) ($codeName): $($_.Count) times"
}

Write-Host "`n--- Timeline ---" -ForegroundColor Cyan
$events | Sort-Object TimeCreated | ForEach-Object {
    $code = if ($_.Message -match '0x[0-9a-fA-F]{8}') { $matches[0] } else { 'N/A' }
    Write-Host "  $($_.TimeCreated.ToString('yyyy-MM-dd HH:mm')) - $code"
}

Write-Host "`n--- Days Between Crashes ---" -ForegroundColor Cyan
$sorted = $events | Sort-Object TimeCreated
for ($i = 1; $i -lt $sorted.Count; $i++) {
    $diff = ($sorted[$i].TimeCreated - $sorted[$i-1].TimeCreated).TotalDays
    Write-Host "  $($sorted[$i-1].TimeCreated.ToString('MM-dd')) -> $($sorted[$i].TimeCreated.ToString('MM-dd')): $([math]::Round($diff,1)) days"
}
