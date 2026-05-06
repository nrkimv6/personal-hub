# pre-commit-plans-block.ps1
#
# 목적: plans 브랜치 외부에서 docs/plan, docs/archive staged commit 자체를 차단한다.
#
# --no-verify 사용 절대 금지

$rootBranchGuard = Join-Path $PSScriptRoot "root-branch-guard.ps1"
if (Test-Path -LiteralPath $rootBranchGuard) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rootBranchGuard -Mode Commit
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$staged = @(git diff --cached --name-only 2>$null)
$branch = git rev-parse --abbrev-ref HEAD 2>$null

# plans 브랜치이면 정상 — 차단 없음
if ($branch -eq "plans") {
    exit 0
}

$planFiles = @($staged | Where-Object { $_ -match "^docs/(plan|archive)/" })
if ($planFiles.Count -eq 0) {
    exit 0
}

Write-Warning "⚠️  [pre-commit hook] docs/plan 또는 docs/archive staged 변경은 plans 브랜치에서만 허용됩니다."
Write-Warning "    차단 사유: disallowed_worktree"
Write-Warning "    현재 브랜치: $branch"
Write-Warning "    staged plan/archive files:"
$planFiles | ForEach-Object { Write-Warning "      - $_" }
Write-Warning "    우회 금지: --no-verify"
Write-Warning "    해결 방법: Set-Location .worktrees/plans 후 해당 문서를 수정/커밋하세요."

exit 1
