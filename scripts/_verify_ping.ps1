$redisCli = Get-ChildItem "C:\", "D:\", "E:\" -Filter "redis-cli.exe" -Recurse -ErrorAction SilentlyContinue -Depth 8 | Select-Object -First 1 -ExpandProperty FullName
Write-Host "redis-cli path: $redisCli"

if ($redisCli) {
    $pingOut = & $redisCli PING 2>$null
    Write-Host "Length: $($pingOut.Length)"
    Write-Host "Bytes: $([System.Text.Encoding]::UTF8.GetBytes($pingOut) -join ' ')"
    Write-Host "Raw eq PONG: $($pingOut -eq 'PONG')"
    Write-Host "Trim eq PONG: $($pingOut.Trim() -eq 'PONG')"
    $runners = & $redisCli SMEMBERS "plan-runner:active_runners" 2>$null
    Write-Host "active_runners: $runners"
} else {
    # python으로 Redis 직접 확인
    $py = "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe"
    $result = & $py -c "import redis; r=redis.Redis(); print('PING:', r.ping()); print('runners:', r.smembers('plan-runner:active_runners'))" 2>$null
    Write-Host "python redis: $result"
}
