$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\lib\components\dev-runner\PlanList.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase B: Eye 아이콘 버튼으로 변경
$old1 = "<button`r`n`t`t`tclass=`"h-6 px-2 text-[10px] rounded text-gray-500 hover:bg-gray-100 transition-colors`"`r`n`t`t`tonclick={toggleIgnored}`r`n`t`t>`r`n`t`t`t{showIgnored ? '활성 보기' : '무시 목록'}`r`n`t`t</button>"
$idx1 = $c.IndexOf($old1)
Write-Host "Eye button idx: $idx1"
if ($idx1 -ge 0) {
    $new1 = "<button`r`n`t`t`tclass=`"h-6 w-6 flex items-center justify-center rounded text-gray-500 hover:bg-gray-100 transition-colors`"`r`n`t`t`tonclick={toggleIgnored}`r`n`t`t`ttitle={showIgnored ? '활성 plan 보기' : '무시 목록 보기'}`r`n`t`t>`r`n`t`t`t{#if showIgnored}`r`n`t`t`t`t<svg class=`"w-3.5 h-3.5`" viewBox=`"0 0 24 24`" fill=`"none`" stroke=`"currentColor`" stroke-width=`"2`"><path d=`"M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24`"/><line x1=`"1`" y1=`"1`" x2=`"23`" y2=`"23`"/></svg>`r`n`t`t`t{:else}`r`n`t`t`t`t<svg class=`"w-3.5 h-3.5`" viewBox=`"0 0 24 24`" fill=`"none`" stroke=`"currentColor`" stroke-width=`"2`"><path d=`"M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z`"/><circle cx=`"12`" cy=`"12`" r=`"3`"/></svg>`r`n`t`t`t{/if}`r`n`t`t</button>"
    $c = $c.Substring(0, $idx1) + $new1 + $c.Substring($idx1 + $old1.Length)
    Write-Host 'Eye button replaced'
}

# Phase B: plan 행 상태 badge w-[70px] 고정폭 + font-mono uppercase + hover opacity 액션들
# 기존 badge 코드 찾기
$badge1 = "plan.status === '구현완료'}`r`n`t\t\t\t\t`t{#if plan.status === '구현완료'}`r`n`t\t\t\t\t\t<span class=`"text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('구현완료')}`">구현완료</span>"
$badgeIdx = $c.IndexOf("text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('구현완료')}")
Write-Host "Badge idx: $badgeIdx"
if ($badgeIdx -ge 0) {
    $ctx = $c.Substring($badgeIdx - 5, 120)
    Write-Host "Context: $ctx"
}

# Replace the status badges with fixed-width mono uppercase
$old2 = "text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('구현완료')}"
$new2 = "w-[70px] text-[10px] font-mono uppercase inline-flex items-center justify-center rounded {statusBadge('구현완료')}"
$c = $c.Replace($old2, $new2)
Write-Host "Badge 구현완료 replaced: $($c.Contains($new2))"

$old3 = "text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded {statusBadge('보류')}"
$new3 = "w-[70px] text-[10px] font-mono uppercase inline-flex items-center justify-center rounded {statusBadge('보류')}"
$c = $c.Replace($old3, $new3)
Write-Host "Badge 보류 replaced: $($c.Contains($new3))"

# Phase B: hover시 액션 버튼 opacity-0 -> group-hover:opacity-100
# button 클래스들에 opacity-0 group-hover:opacity-100 추가
$old4 = 'class="shrink-0 p-1 rounded hover:bg-green-100 disabled:opacity-50"'
$new4 = 'class="shrink-0 p-1 rounded hover:bg-green-100 disabled:opacity-50 opacity-0 group-hover:opacity-100 transition-opacity"'
$c = $c.Replace($old4, $new4)
Write-Host "Done btn opacity: $($c.Contains($new4))"

$old5 = 'class="shrink-0 p-1 rounded hover:bg-yellow-100"'
$new5 = 'class="shrink-0 p-1 rounded hover:bg-yellow-100 opacity-0 group-hover:opacity-100 transition-opacity"'
$c = $c.Replace($old5, $new5)
Write-Host "Hold btn opacity: $($c.Contains($new5))"

$old6 = 'class="shrink-0 p-1 rounded hover:bg-blue-100"'
$new6 = 'class="shrink-0 p-1 rounded hover:bg-blue-100 opacity-0 group-hover:opacity-100 transition-opacity"'
$c = $c.Replace($old6, $new6)
Write-Host "Unhold btn opacity: $($c.Contains($new6))"

# plan 행에 group 클래스 추가 (hover 액션 동작을 위해)
$old7 = 'class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left transition-colors w-full'
$new7 = 'class="group flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left transition-colors w-full'
$c = $c.Replace($old7, $new7)
Write-Host "group class: $($c.Contains($new7))"

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'Done'
