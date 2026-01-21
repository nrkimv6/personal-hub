# BSOD Analysis Script
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== BSOD History (Last 30 days) ===" -ForegroundColor Cyan
$bsodEvents = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue

foreach ($event in $bsodEvents) {
    Write-Host "`n--- $($event.TimeCreated) ---" -ForegroundColor Yellow
    Write-Host $event.Message
}

Write-Host "`n=== Recent Driver Events ===" -ForegroundColor Cyan
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-PnP'; Level=2,3; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 10 -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "`n$($_.TimeCreated): $($_.Message)"
}

Write-Host "`n=== System File Checker Log ===" -ForegroundColor Cyan
$sfcLog = Get-Content "$env:windir\Logs\CBS\CBS.log" -Tail 50 -ErrorAction SilentlyContinue | Select-String -Pattern "corrupt|error" -SimpleMatch
if ($sfcLog) { $sfcLog | ForEach-Object { Write-Host $_ } }
else { Write-Host "No corruption found in recent SFC logs" }
