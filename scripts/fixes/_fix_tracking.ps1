$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\routes\automation\DevRunnerTab.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase E: 상단 CurrentTrackingCard 블록 제거 (좌측 Tasks 탭에만 유지)
$topBlock = "`r`n`t`t`t<!-- CurrentTrackingCard (???? ?? + ???? ???? ????) -->`r`n`t`t`t{#if activeTabRunner?.running && currentTracking}`r`n`t`t`t\t<div class=`"px-4 py-2 border-b bg-gray-50 shrink-0`">`r`n`t`t`t\t\t<CurrentTrackingCard tracking={currentTracking} />`r`n`t`t`t\t</div>`r`n`t`t`t{/if}"
$topIdx = $c.IndexOf($topBlock)
Write-Host "Top block idx (Korean): $topIdx"

# Try without Korean comment
$topBlock2 = "`r`n`r`n`t`t`t<!-- CurrentTrackingCard"
$topIdx2 = $c.IndexOf($topBlock2)
Write-Host "Top block2 idx: $topIdx2"
if ($topIdx2 -ge 0) {
    Write-Host $c.Substring($topIdx2, 250)
}

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'Done'
