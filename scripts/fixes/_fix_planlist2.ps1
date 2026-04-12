$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\lib\components\dev-runner\PlanList.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase B: toggle eye icon button
$oldToggle = "class=`"h-6 px-2 text-[10px] rounded text-gray-500 hover:bg-gray-100 transition-colors`""
$idxToggle = $c.IndexOf($oldToggle)
Write-Host "toggle idx: $idxToggle"
if ($idxToggle -ge 0) {
    $newToggle = "class=`"h-6 w-6 flex items-center justify-center rounded text-gray-500 hover:bg-gray-100 transition-colors`""
    $c = $c.Substring(0, $idxToggle) + $newToggle + $c.Substring($idxToggle + $oldToggle.Length)
    Write-Host 'toggle class replaced'
}

# Find and replace toggle button content (Korean text)
$toggleContent = "`r`n`t`t`t{showIgnored ? "
$idxContent = $c.IndexOf($toggleContent)
Write-Host "Toggle content idx: $idxContent"
if ($idxContent -ge 0) {
    $endIdx = $c.IndexOf("`r`n`t`t</button>", $idxContent)
    Write-Host "End idx: $endIdx"
    $before = $c.Substring(0, $idxContent)
    $after = $c.Substring($endIdx)
    $newContent = "`r`n`t`t`t{#if showIgnored}`r`n`t`t`t`t<svg class=`"w-3.5 h-3.5`" viewBox=`"0 0 24 24`" fill=`"none`" stroke=`"currentColor`" stroke-width=`"2`"><path d=`"M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24`"/><line x1=`"1`" y1=`"1`" x2=`"23`" y2=`"23`"/></svg>`r`n`t`t`t{:else}`r`n`t`t`t`t<svg class=`"w-3.5 h-3.5`" viewBox=`"0 0 24 24`" fill=`"none`" stroke=`"currentColor`" stroke-width=`"2`"><path d=`"M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z`"/><circle cx=`"12`" cy=`"12`" r=`"3`"/></svg>`r`n`t`t`t{/if}`r`n`t`t"
    $c = $before + $newContent + $after
    Write-Host 'Toggle content replaced'
}

# Phase B: badge fixed width
$oldBadge1 = "text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('구현완료')}"
$badgeIdx1 = $c.IndexOf($oldBadge1)
Write-Host "badge1 idx: $badgeIdx1"
if ($badgeIdx1 -ge 0) {
    $newBadge1 = "w-[70px] text-[10px] font-mono uppercase inline-flex items-center justify-center rounded {statusBadge('구현완료')}"
    $c = $c.Substring(0, $badgeIdx1) + $newBadge1 + $c.Substring($badgeIdx1 + $oldBadge1.Length)
    Write-Host 'badge1 replaced'
}

$oldBadge2 = "text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('보류')}"
$badgeIdx2 = $c.IndexOf($oldBadge2)
Write-Host "badge2 idx: $badgeIdx2"
if ($badgeIdx2 -ge 0) {
    $newBadge2 = "w-[70px] text-[10px] font-mono uppercase inline-flex items-center justify-center rounded {statusBadge('보류')}"
    $c = $c.Substring(0, $badgeIdx2) + $newBadge2 + $c.Substring($badgeIdx2 + $oldBadge2.Length)
    Write-Host 'badge2 replaced'
}

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'Done'
