[Console]::OutputEncoding=[System.Text.Encoding]::UTF8

$candidates = @(
    'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe',
    'C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe',
    'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\windbg.exe',
    'C:\Program Files\Windows Kits\10\Debuggers\x64\windbg.exe'
)
foreach ($p in $candidates) {
    if (Test-Path $p) { Write-Host "FOUND: $p" }
}

Write-Host ""
Write-Host "=== Glob search ==="
Get-ChildItem 'C:\Program Files*\Windows Kits\*\Debuggers\x64\cdb.exe' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName

Write-Host ""
Write-Host "=== WindowsApps (Store WinDbg) ==="
Get-ChildItem 'C:\Program Files\WindowsApps\Microsoft.WinDbg*\*.exe' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName
