# Driver Analysis Script
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== Third-Party Kernel Drivers ===" -ForegroundColor Cyan
$drivers = Get-CimInstance Win32_SystemDriver | Where-Object {
    $_.PathName -and
    $_.PathName -notlike "*\Windows\*" -and
    $_.State -eq 'Running'
}
$drivers | Format-Table Name, DisplayName, PathName -AutoSize

Write-Host "`n=== Recently Modified Drivers (7 days) ===" -ForegroundColor Cyan
Get-ChildItem "C:\Windows\System32\drivers" -Filter "*.sys" |
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-7) } |
    Sort-Object LastWriteTime -Descending |
    Select-Object Name, LastWriteTime, @{N='SizeKB';E={[math]::Round($_.Length/1KB,1)}}

Write-Host "`n=== Non-Microsoft Drivers in System32\drivers ===" -ForegroundColor Cyan
Get-ChildItem "C:\Windows\System32\drivers" -Filter "*.sys" | ForEach-Object {
    $sig = Get-AuthenticodeSignature $_.FullName -ErrorAction SilentlyContinue
    if ($sig -and $sig.SignerCertificate -and $sig.SignerCertificate.Subject -notlike "*Microsoft*") {
        [PSCustomObject]@{
            Name = $_.Name
            Signer = ($sig.SignerCertificate.Subject -split ',')[0] -replace 'CN=',''
            Date = $_.LastWriteTime
        }
    }
} | Sort-Object Signer | Format-Table -AutoSize

Write-Host "`n=== GPU Driver Info ===" -ForegroundColor Cyan
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, DriverDate
