[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$OutputEncoding=[System.Text.Encoding]::UTF8

Write-Host "=== WHEA-Logger (last 20) ==="
$whea = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 20 -ErrorAction SilentlyContinue
if ($whea) {
    $whea | Select-Object TimeCreated, Id, LevelDisplayName | Format-Table -AutoSize
} else {
    Write-Host "No WHEA events"
}

Write-Host ""
Write-Host "=== BugCheck distribution (last 30 days) ==="
Get-WinEvent -FilterHashtable @{LogName='System'; ID=1001; StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue |
    ForEach-Object {
        if ($_.Message -match '0x[0-9a-fA-F]{8}') {
            $matches[0]
        }
    } | Group-Object | Sort-Object Count -Descending | Format-Table Count, Name -AutoSize

Write-Host ""
Write-Host "=== OS boot time ==="
$os = Get-CimInstance Win32_OperatingSystem
$os | Select-Object LastBootUpTime, LocalDateTime | Format-List

Write-Host ""
Write-Host "=== Memory modules ==="
Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer, PartNumber, Capacity, Speed, ConfiguredClockSpeed, DeviceLocator | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Disk health ==="
Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus, OperationalStatus, Size | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Thermal zones (if supported) ==="
try {
    Get-CimInstance -Namespace 'root/wmi' -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop |
        Select-Object InstanceName, @{n='Celsius';e={[math]::Round(($_.CurrentTemperature / 10) - 273.15, 1)}} |
        Format-Table -AutoSize
} catch {
    Write-Host "Thermal WMI not supported"
}

Write-Host ""
Write-Host "=== MemoryDiagnostic-Results ==="
Get-WinEvent -LogName 'Microsoft-Windows-MemoryDiagnostics-Results/Debug' -MaxEvents 5 -ErrorAction SilentlyContinue | Select-Object TimeCreated, Id, Message | Format-List
