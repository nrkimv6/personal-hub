[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$OutputEncoding=[System.Text.Encoding]::UTF8

Write-Host "=== Kernel-Power 41 (상세) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; ID=41} -MaxEvents 5 | ForEach-Object {
    $x = [xml]$_.ToXml()
    $props = @{}
    $x.Event.EventData.Data | ForEach-Object { $props[$_.Name] = $_.'#text' }
    [PSCustomObject]@{
        Time                        = $_.TimeCreated
        BugcheckCode                = $props['BugcheckCode']
        BugcheckParameter1          = $props['BugcheckParameter1']
        PowerButtonTimestamp        = $props['PowerButtonTimestamp']
        SleepInProgress             = $props['SleepInProgress']
        LongPowerButtonPressDetected= $props['LongPowerButtonPressDetected']
    }
} | Format-List

Write-Host ""
Write-Host "=== BugCheck 이벤트 (ID 1001) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; ID=1001} -MaxEvents 5 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Id, ProviderName, Message | Format-List

Write-Host ""
Write-Host "=== WHEA-Logger (하드웨어 오류) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 10 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Id, LevelDisplayName | Format-Table -AutoSize

Write-Host ""
Write-Host "=== 2026-04-11 08:30~09:10 에러/경고 이벤트 ==="
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date '2026-04-11 08:30:00'); EndTime=(Get-Date '2026-04-11 09:10:00')} -ErrorAction SilentlyContinue |
    Where-Object { $_.LevelDisplayName -in 'Error','Critical','Warning' } |
    Select-Object TimeCreated, Id, LevelDisplayName, ProviderName |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== MEMORY.DMP 존재 확인 ==="
if (Test-Path "$env:SystemRoot\MEMORY.DMP") {
    Get-Item "$env:SystemRoot\MEMORY.DMP" | Select-Object FullName, Length, LastWriteTime | Format-List
} else {
    Write-Host "MEMORY.DMP 없음"
}
Get-ChildItem "$env:SystemRoot\Minidump\*.dmp" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName, LastWriteTime | Format-List
