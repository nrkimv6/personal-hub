$wt = 'D:\work\project\tools\monitor-page\.worktrees\impl-dev-runner-design-port-v2\frontend'
$main = 'D:\work\project\tools\monitor-page\frontend'

# node_modules junction
if (-not (Test-Path "$wt\node_modules")) {
    New-Item -ItemType Junction -Path "$wt\node_modules" -Target "$main\node_modules" | Out-Null
    Write-Host 'node_modules junction created'
} else {
    Write-Host 'node_modules already exists'
}

# .svelte-kit junction
if (-not (Test-Path "$wt\.svelte-kit")) {
    New-Item -ItemType Junction -Path "$wt\.svelte-kit" -Target "$main\.svelte-kit" | Out-Null
    Write-Host '.svelte-kit junction created'
} else {
    Write-Host '.svelte-kit already exists'
}

Write-Host 'Done'
