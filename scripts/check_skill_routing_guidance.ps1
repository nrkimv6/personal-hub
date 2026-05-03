param(
    [string]$MonitorPageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$WtoolsRoot = "D:\work\project\service\wtools"
)

$ErrorActionPreference = "Stop"

$skillRelPaths = @(
    ".claude\skills\implement\SKILL.md",
    ".claude\skills\done\SKILL.md",
    ".claude\skills\merge-test\SKILL.md",
    ".agents\skills\implement\SKILL.md",
    ".agents\skills\done\SKILL.md",
    ".agents\skills\merge-test\SKILL.md"
)

$roots = @($WtoolsRoot, $MonitorPageRoot)
$required = @(
    "branch/worktree present -> /merge-test; absent -> /done",
    "/merge-test",
    "/done"
)

$failures = @()
foreach ($root in $roots) {
    foreach ($rel in $skillRelPaths) {
        $path = Join-Path $root $rel
        if (-not (Test-Path $path)) {
            $failures += "missing: $path"
            continue
        }

        $text = Get-Content -Raw $path
        foreach ($needle in $required) {
            if (-not $text.Contains($needle)) {
                $failures += "missing '$needle': $path"
            }
        }
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "skill routing guidance is consistent"
