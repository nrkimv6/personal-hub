# redis-cli 경로 찾기
$redisCli = Get-Command redis-cli -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $redisCli) {
    $candidates = @(
        "C:\Program Files\Redis\redis-cli.exe",
        "C:\tools\Redis\redis-cli.exe",
        "C:\Redis\redis-cli.exe",
        "C:\ProgramData\chocolatey\bin\redis-cli.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { $redisCli = $c; break } }
}
if (-not $redisCli) {
    $redisCli = Get-ChildItem "C:\", "D:\" -Filter "redis-cli.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 | Select-Object -First 1 -ExpandProperty FullName
}
Write-Host "redis-cli path: $redisCli"

if ($redisCli) {
    $pingOut = & $redisCli PING 2>$null
    Write-Host "Length: $($pingOut.Length)"
    Write-Host "Bytes: $([System.Text.Encoding]::UTF8.GetBytes($pingOut) -join ' ')"
    Write-Host "Raw eq PONG: $($pingOut -eq 'PONG')"
    Write-Host "Trim eq PONG: $($pingOut.Trim() -eq 'PONG')"

    # active_runners 확인
    $runners = & $redisCli SMEMBERS "plan-runner:active_runners" 2>$null
    Write-Host "active_runners: $runners"
    foreach ($rid in $runners) {
        $rid = $rid.Trim()
        if (-not $rid) { continue }
        $logPath = & $redisCli GET "plan-runner:runners:${rid}:log_file_path" 2>$null
        Write-Host "  runner=$rid logPath=$logPath"
    }
} else {
    Write-Host "redis-cli not found"
}
