$wt = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend'
Set-Location $wt

# .svelte-kit 제거 (junction이면 cmd rmdir 사용)
if (Test-Path '.svelte-kit') {
    $attr = (Get-Item '.svelte-kit').Attributes
    Write-Host "Attr: $attr"
    # ReparsePoint = junction/symlink
    if ($attr -band [System.IO.FileAttributes]::ReparsePoint) {
        cmd /c "rmdir `"$wt\.svelte-kit`"" 2>&1 | Out-Null
        Write-Host 'junction removed'
    } else {
        Remove-Item '.svelte-kit' -Recurse -Force
        Write-Host 'directory removed'
    }
}

# sync
Write-Host 'Running svelte-kit sync...'
& "$wt\node_modules\.bin\svelte-kit.cmd" sync 2>&1 | Write-Host
Write-Host 'Sync done'

# build
Write-Host 'Building...'
& "$wt\node_modules\.bin\vite.cmd" build 2>&1 | Select-Object -Last 10
