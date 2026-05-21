param(
    [switch]$Json,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$allowedArtifactRoots = @(".tmp/codex/", ".tmp/codex-browser-artifacts/", "logs/")

function ConvertTo-RelativeGitPath {
    param([string]$PathValue)
    return $PathValue.Trim().Replace('\', '/')
}

function Get-RepoRoot {
    $root = git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) {
        throw "not_a_git_repository"
    }
    return $root.Trim()
}

function Get-UntrackedFiles {
    $raw = git ls-files --others --exclude-standard 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git_untracked_scan_failed"
    }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { ConvertTo-RelativeGitPath $_ })
}

function Get-UntrackedPathsWithDirectories {
    $raw = git ls-files --others --exclude-standard --directory 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git_untracked_dir_scan_failed"
    }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { ConvertTo-RelativeGitPath $_ })
}

function Get-ArtifactClassification {
    param([string]$PathValue)

    $name = [System.IO.Path]::GetFileName($PathValue)
    $extension = [System.IO.Path]::GetExtension($name).ToLowerInvariant()

    if ($name -like "modernhouse-*") {
        return "modernhouse-browser-artifact"
    }
    if ($name -like "naver-popupstore-*") {
        return "naver-popupstore-browser-artifact"
    }
    if ($name -match "(?i)-snapshot\.md$") {
        return "browser-snapshot"
    }
    if ($name -match "(?i)-evidence-.*\.json$") {
        return "browser-evidence-json"
    }
    if ($extension -in @(".png", ".jpg", ".jpeg", ".webp")) {
        return "root-image-dump"
    }
    if ($extension -eq ".json" -and $name -match "(?i)(dump|snapshot|evidence|browser|screenshot|artifact|capture)") {
        return "root-json-dump"
    }

    return $null
}

$artifactDirNames = @("tmp", "temp", "screenshots", "captures", "playwright-report", "test-results")
function Get-RootDirArtifactClassification {
    param([string]$PathValue)
    $trimmed = $PathValue.TrimEnd('/')
    $name = [System.IO.Path]::GetFileName($trimmed)
    if ($artifactDirNames -contains $name) {
        return "root-untracked-dir-artifact"
    }
    return $null
}

$repoRoot = Get-RepoRoot
$untracked = Get-UntrackedFiles
$untrackedWithDirs = Get-UntrackedPathsWithDirectories
$rootFiles = @($untracked | Where-Object {
    $_ -notmatch "/" -and (Test-Path -LiteralPath (Join-Path $repoRoot $_) -PathType Leaf)
})
$rootDirs = @($untrackedWithDirs | Where-Object {
    ($_.TrimEnd('/') -notmatch "/") -and (Test-Path -LiteralPath (Join-Path $repoRoot $_) -PathType Container)
})

$artifacts = @()
$unrelatedRootFiles = @()
foreach ($path in $rootFiles) {
    $classification = Get-ArtifactClassification $path
    if ([string]::IsNullOrWhiteSpace($classification)) {
        $unrelatedRootFiles += $path
        continue
    }

    $artifacts += [pscustomobject]@{
        path = $path
        classification = $classification
        recommendation = "Delete if disposable, or move intentional evidence under .tmp/codex/<plan-slug>/<timestamp>/ (preferred), or .tmp/codex-browser-artifacts/ (compat), or logs/."
    }
}

$unrelatedRootDirs = @()
foreach ($path in $rootDirs) {
    $classification = Get-RootDirArtifactClassification $path
    if ([string]::IsNullOrWhiteSpace($classification)) {
        $unrelatedRootDirs += $path
        continue
    }

    $artifacts += [pscustomobject]@{
        path = $path
        classification = $classification
        recommendation = "Delete if disposable, or move intentional evidence under .tmp/codex/<plan-slug>/<timestamp>/ (preferred), or .tmp/codex-browser-artifacts/ (compat), or logs/."
    }
}

$result = [pscustomobject]@{
    repoRoot = $repoRoot
    allowedArtifactRoots = $allowedArtifactRoots
    untrackedRootFileCount = $rootFiles.Count
    untrackedRootDirCount = $rootDirs.Count
    artifactCount = $artifacts.Count
    artifacts = $artifacts
    unrelatedRootFiles = $unrelatedRootFiles
    unrelatedRootDirs = $unrelatedRootDirs
}

if ($Json) {
    $result | ConvertTo-Json -Depth 5
} elseif ($artifacts.Count -gt 0) {
    [Console]::Error.WriteLine("codex_browser_artifact_root_dirty_detected: root-level untracked browser/Codex artifact candidates were found.")
    [Console]::Error.WriteLine("allowed evidence paths: .tmp/codex/<plan-slug>/<timestamp>/ (preferred), .tmp/codex-browser-artifacts/ (compat), or logs/")
    [Console]::Error.WriteLine("affected files:")
    foreach ($artifact in $artifacts) {
        [Console]::Error.WriteLine("  - $($artifact.path) [$($artifact.classification)]")
    }
    [Console]::Error.WriteLine("recommended recovery: delete disposable investigation output, or move intentional evidence under an allowed ignored path before committing.")
} elseif (-not $Quiet) {
    Write-Output "codex_browser_artifact_guard_clean"
    if ($unrelatedRootFiles.Count -gt 0) {
        Write-Output "unrelated_root_untracked_count=$($unrelatedRootFiles.Count)"
    }
}

if ($artifacts.Count -gt 0) {
    exit 1
}
exit 0
