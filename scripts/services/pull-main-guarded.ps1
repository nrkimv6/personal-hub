param(
    [string]$Remote = "origin",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($currentBranch -ne "main") {
    throw "pull-main-guarded requires root main checkout; current branch=$currentBranch"
}

git fetch $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$candidate = "FETCH_HEAD"
$checker = Join-Path $repoRoot "scripts\diagnostics\check-candidate-tip.ps1"
$json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checker -CurrentMain HEAD -CandidateTip $candidate
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("candidate_tip_check_failed")
    exit 1
}

$result = $json | ConvertFrom-Json
$blockers = @($result.blockers)
if ($blockers.Count -gt 0) {
    [Console]::Error.WriteLine("candidate_tip_guard_blocked: blockers=$($blockers -join ', ')")
    [Console]::Error.WriteLine($json)
    exit 1
}

git merge --ff-only $candidate
exit $LASTEXITCODE
