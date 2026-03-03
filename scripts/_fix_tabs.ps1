$path = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend\src\routes\automation\DevRunnerTab.svelte'
$c = [System.IO.File]::ReadAllText($path)

# Phase C: max-w-sm -> max-w-md
$old1 = 'max-w-sm'
$idx1 = $c.IndexOf($old1)
Write-Host "max-w-sm idx: $idx1"
if ($idx1 -ge 0) {
    $c = $c.Substring(0, $idx1) + 'max-w-md' + $c.Substring($idx1 + $old1.Length)
    Write-Host 'max-w-md replaced'
}

# Phase D: Logs/Merge active tab style: bg-blue-50 -> bg-primary/20
# These two occurrences use text-gray-500 (not text-gray-600 like runner tabs)
$old2a = "bg-blue-50 text-blue-700 border border-blue-200' : 'text-gray-500 hover:bg-gray-100'}"
$new2a = "bg-primary/20 text-primary border border-primary/30' : 'text-gray-500 hover:bg-gray-100'}"
$cnt2 = 0
while ($c.Contains($old2a)) {
    $idx = $c.IndexOf($old2a)
    $c = $c.Substring(0, $idx) + $new2a + $c.Substring($idx + $old2a.Length)
    $cnt2++
}
Write-Host "Logs/Merge style replaced: $cnt2 times"

# Phase D: Logs emoji -> Terminal SVG (using unicode codepoint)
$logsEmoji = [System.Text.Encoding]::UTF8.GetString([byte[]](0xF0, 0x9F, 0x93, 0x8B))  # 📋
$logsOld = "<span>$logsEmoji</span>"
$logsNew = '<svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>'
$logsIdx = $c.IndexOf($logsOld)
Write-Host "Logs emoji idx: $logsIdx"
if ($logsIdx -ge 0) {
    $c = $c.Substring(0, $logsIdx) + $logsNew + $c.Substring($logsIdx + $logsOld.Length)
    Write-Host 'Logs emoji replaced'
}

# Phase D: Merge emoji -> GitMerge SVG
$mergeEmoji = [System.Text.Encoding]::UTF8.GetString([byte[]](0xF0, 0x9F, 0x94, 0x80))  # 🔀
$mergeOld = "<span>$mergeEmoji</span>"
$mergeNew = '<svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>'
$mergeIdx = $c.IndexOf($mergeOld)
Write-Host "Merge emoji idx: $mergeIdx"
if ($mergeIdx -ge 0) {
    $c = $c.Substring(0, $mergeIdx) + $mergeNew + $c.Substring($mergeIdx + $mergeOld.Length)
    Write-Host 'Merge emoji replaced'
}

[System.IO.File]::WriteAllText($path, $c)
Write-Host 'File saved'
