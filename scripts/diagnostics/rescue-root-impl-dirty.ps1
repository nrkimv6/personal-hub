param(
    [switch]$Apply,
    [string]$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$RescueName = ""
)

$ErrorActionPreference = "Stop"

function ConvertTo-GitPath {
    param([string]$PathValue)
    return $PathValue.Trim().Replace('\', '/')
}

function Get-StatusPath {
    param([string]$Line)
    $raw = if ($Line.Length -ge 3) { $Line.Substring(3).Trim() } else { $Line.Trim() }
    if ($raw -match " -> ") {
        $raw = ($raw -split " -> ", 2)[1].Trim()
    }
    return ConvertTo-GitPath $raw
}

function Get-PathClass {
    param([string]$PathValue)
    $p = ConvertTo-GitPath $PathValue
    if ($p -match "^\.agents/" -or $p -match "^\.agent/" -or $p -match "^\.claude/" -or $p -match "^\.gemini/") {
        return "mirror"
    }
    if ($p -in @("AGENTS.md", "CLAUDE.md", "MANUAL_TASKS.md", "CHANGELOG.md", ".gitignore", "TODO.md") -or $p -match "^docs/(plan/|archive/|DONE\.md)") {
        return "docs_lineage"
    }
    if ($p -match "^(app|frontend|scripts|tests|alembic|migrations|data|common)/" -or $p -match "\.(py|ps1|ts|js|svelte|css|json|sql)$") {
        return "implementation"
    }
    return "unknown"
}

$root = (Resolve-Path -LiteralPath $RepoRoot).Path
$top = (& git -C $root rev-parse --show-toplevel 2>$null).Trim()
if (-not $top) {
    throw "not a git worktree: $root"
}
$branch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim()
$commonGitDir = (& git -C $root rev-parse --git-common-dir).Trim()
if (-not [System.IO.Path]::IsPathRooted($commonGitDir)) {
    $commonGitDir = Join-Path $top $commonGitDir
}
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $commonGitDir)).Path
$isRootCheckout = ((Resolve-Path -LiteralPath $top).Path -eq $projectRoot)

$statusLines = @(& git -C $root status --porcelain=v1)
$items = foreach ($line in $statusLines) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $path = Get-StatusPath $line
    [pscustomobject]@{
        Status = $line.Substring(0, [Math]::Min(2, $line.Length))
        Path = $path
        Class = Get-PathClass $path
    }
}

$implementation = @($items | Where-Object { $_.Class -eq "implementation" })
$mirror = @($items | Where-Object { $_.Class -eq "mirror" })
$docsLineage = @($items | Where-Object { $_.Class -eq "docs_lineage" })
$unknown = @($items | Where-Object { $_.Class -eq "unknown" })

Write-Output "repo_root=$top"
Write-Output "project_root=$projectRoot"
Write-Output "branch=$branch"
Write-Output "is_root_checkout=$isRootCheckout"
Write-Output "mode=$(if ($Apply) { 'apply' } else { 'dry-run' })"
Write-Output "implementation_count=$($implementation.Count)"
$implementation | ForEach-Object { Write-Output "implementation_path=$($_.Path)" }
Write-Output "docs_lineage_count=$($docsLineage.Count)"
$docsLineage | ForEach-Object { Write-Output "docs_lineage_path=$($_.Path)" }
Write-Output "mirror_count=$($mirror.Count)"
$mirror | ForEach-Object { Write-Output "mirror_path=$($_.Path)" }
Write-Output "unknown_count=$($unknown.Count)"
$unknown | ForEach-Object { Write-Output "unknown_path=$($_.Path)" }

if (-not $Apply) {
    Write-Output "dry_run_no_mutation=true"
    Write-Output "next_step=rerun with -Apply only after confirming implementation_path entries belong in the rescue worktree"
    exit 0
}

if (-not $isRootCheckout -or $branch -ne "main") {
    throw "Apply requires the root main checkout. current branch=$branch is_root_checkout=$isRootCheckout"
}
if ($mirror.Count -gt 0) {
    throw "mirror surface dirty detected; stop and use receiver mirror sync policy before rescue apply"
}
if ($implementation.Count -eq 0) {
    Write-Output "apply_noop=true"
    exit 0
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($RescueName)) {
    $RescueName = "codex/root-dirty-rescue-$timestamp"
}
$safeWorktreeName = $RescueName.Replace('/', '-').Replace('\', '-')
$worktreePath = Join-Path $top ".worktrees\$safeWorktreeName"
$stashName = "root-dirty-rescue $timestamp"
$implPaths = @($implementation | ForEach-Object { $_.Path })

& git -C $top stash push -u -m $stashName -- @implPaths
if ($LASTEXITCODE -ne 0) {
    throw "git stash push failed"
}
$stashRef = (& git -C $top stash list --format="%gd %s" | Select-Object -First 1)
if (-not ($stashRef -match "^(stash@\{\d+\})\s")) {
    throw "could not resolve created stash ref"
}
$stashRef = $Matches[1]

& git -C $top worktree add $worktreePath -b $RescueName main
if ($LASTEXITCODE -ne 0) {
    throw "git worktree add failed"
}

& git -C $worktreePath stash apply $stashRef
if ($LASTEXITCODE -ne 0) {
    throw "git stash apply failed in rescue worktree; stash preserved as $stashRef"
}

$remaining = @(& git -C $top status --porcelain=v1 -- @implPaths)
Write-Output "stash_ref=$stashRef"
Write-Output "rescue_branch=$RescueName"
Write-Output "rescue_worktree=$worktreePath"
Write-Output "root_impl_dirty_remaining=$($remaining.Count)"
if ($remaining.Count -eq 0) {
    Write-Output "root_clean_for_implementation=true"
} else {
    $remaining | ForEach-Object { Write-Output "root_remaining=$_" }
}
