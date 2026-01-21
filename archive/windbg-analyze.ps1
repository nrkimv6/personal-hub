# WinDbg Analysis Script
# Create analysis script for WinDbg
$analyzeScript = @"
.sympath srv*C:\Symbols*https://msdl.microsoft.com/download/symbols
.reload
!analyze -v
!process 0 0
lm
q
"@

$scriptPath = "D:\work\project\tools\monitor-page\windbg-commands.txt"
$analyzeScript | Out-File -FilePath $scriptPath -Encoding ASCII

Write-Host "WinDbg analysis script created at: $scriptPath" -ForegroundColor Green
Write-Host ""
Write-Host "To analyze the dump file, run WinDbg with:" -ForegroundColor Cyan
Write-Host 'WinDbgX.exe -z "C:\WINDOWS\MEMORY.DMP" -c "$<D:\work\project\tools\monitor-page\windbg-commands.txt"'
Write-Host ""
Write-Host "Or open WinDbg GUI and:" -ForegroundColor Yellow
Write-Host "1. File -> Open dump file -> C:\WINDOWS\MEMORY.DMP"
Write-Host "2. Run command: !analyze -v"
