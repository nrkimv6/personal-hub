$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\routes\automation\DevRunnerTab.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase A: RunStatusBar에 onStopRunner, onKillRunner 추가 (3탭 들여쓰기)
$marker = '} : undefined}' + "`r`n`t`t`t/>"
$idx = $c.IndexOf($marker)
Write-Host "StopAll marker idx: $idx"
if ($idx -ge 0) {
    $repl = '} : undefined}' + "`r`n`t`t`tonStopRunner={async (id) => { await devRunnerRunnerApi.stop(id).catch(() => {}); void pollStatus(); }}" + "`r`n`t`t`tonKillRunner={async (id) => { await devRunnerRunnerApi.kill(id).catch(() => {}); void pollStatus(); }}" + "`r`n`t`t`t/>"
    $c = $c.Substring(0, $idx) + $repl + $c.Substring($idx + $marker.Length)
    Write-Host 'Phase A: stop/kill runner props added to RunStatusBar'
}

# Phase C 검증
$mcIdx = $c.IndexOf('max-w-sm')
Write-Host "max-w-sm idx: $mcIdx"

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'Done'
