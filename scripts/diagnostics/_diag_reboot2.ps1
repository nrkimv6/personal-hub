[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$OutputEncoding=[System.Text.Encoding]::UTF8

Write-Host "=== 18:00~18:40 시스템 이벤트 (Error/Critical/Warning) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date '2026-04-11 18:00:00'); EndTime=(Get-Date '2026-04-11 18:40:00')} -ErrorAction SilentlyContinue |
    Where-Object { $_.LevelDisplayName -in 'Error','Critical','Warning' } |
    Select-Object TimeCreated, Id, LevelDisplayName, ProviderName |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== 07:00~07:20 시스템 이벤트 (Error/Critical/Warning) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date '2026-04-11 07:00:00'); EndTime=(Get-Date '2026-04-11 07:20:00')} -ErrorAction SilentlyContinue |
    Where-Object { $_.LevelDisplayName -in 'Error','Critical','Warning' } |
    Select-Object TimeCreated, Id, LevelDisplayName, ProviderName |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== 09:00~09:15 시스템 이벤트 (Error/Critical/Warning) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date '2026-04-11 09:00:00'); EndTime=(Get-Date '2026-04-11 09:15:00')} -ErrorAction SilentlyContinue |
    Where-Object { $_.LevelDisplayName -in 'Error','Critical','Warning' } |
    Select-Object TimeCreated, Id, LevelDisplayName, ProviderName |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== BugCheck 1001 (최근 10개 전체 메시지) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; ID=1001} -MaxEvents 10 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, @{n='Msg';e={$_.Message}} | Format-List
