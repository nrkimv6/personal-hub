param(
    [string]$SquashMerge = ""
)

$ErrorActionPreference = "Stop"

$script = Join-Path (Split-Path -Parent $PSScriptRoot) "diagnostics\check-candidate-tip.ps1"
if (-not (Test-Path -LiteralPath $script)) {
    exit 0
}

try {
    git rev-parse --verify ORIG_HEAD 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        exit 0
    }

    $json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -CurrentMain ORIG_HEAD -CandidateTip HEAD
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("post_merge_candidate_tip_check_failed: check-candidate-tip exited $code")
        exit 0
    }
    $result = $json | ConvertFrom-Json
    $blockers = @($result.blockers)
    if ($blockers.Count -gt 0) {
        $sentinel = git rev-parse --git-path candidate-tip-violation.json
        $json | Set-Content -LiteralPath $sentinel -Encoding UTF8
        [Console]::Error.WriteLine("post_merge_candidate_tip_violation: blockers=$($blockers -join ', ') sentinel=$sentinel")
    }
} catch {
    [Console]::Error.WriteLine("post_merge_candidate_tip_check_error: $($_.Exception.Message)")
}

exit 0
