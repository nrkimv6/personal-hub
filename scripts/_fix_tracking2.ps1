$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\routes\automation\DevRunnerTab.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase E-1: 상단 CurrentTrackingCard 블록 제거
$startMarker = "`r`n`r`n`t`t`t<!-- CurrentTrackingCard"
$endMarker = "`r`n`t`t`t{/if}`r`n`r`n`t`t`t<!-- ??? ?? -->"

$startIdx = $c.IndexOf($startMarker)
Write-Host "Start idx: $startIdx"

$endIdx = $c.IndexOf($endMarker)
Write-Host "End idx: $endIdx"

if ($startIdx -ge 0 -and $endIdx -gt $startIdx) {
    # Remove the top CurrentTrackingCard block (keep the empty line before next section)
    $removeEnd = $endIdx  # keep from here
    $c = $c.Substring(0, $startIdx) + "`r`n" + $c.Substring($removeEnd)
    Write-Host "Top block removed"
}

# Phase E-2: Tasks 탭 내 currentTracking 조건에서 running 제거
$old2 = "{#if activeTabRunner?.running && currentTracking}"
$new2 = "{#if currentTracking}"
$cnt2 = ($c.Split($old2).Length - 1)
Write-Host "running condition count: $cnt2"
$c = $c.Replace($old2, $new2)

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'Done'
