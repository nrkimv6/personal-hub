# pre-commit-plans-warn.ps1
# 경고 모드 (차단 없음) — plan-isolation-4-cutover 완료 후 pre-commit-plans-block.ps1로 교체
#
# 목적: main/impl 브랜치에서 docs/plan/, docs/archive/ 커밋 시도를 감지해 경고 출력
# 차단 모드로 전환 시: exit 0 → exit 1 + 파일명 warn → block 변경
#
# 우회 절차: docs/plan 수정은 'cd .worktrees/plans' 후 작업
# --no-verify 사용 절대 금지

$staged = git diff --cached --name-only 2>$null
$branch = git rev-parse --abbrev-ref HEAD 2>$null

# plans 브랜치이면 정상 — 경고 없음
if ($branch -eq "plans") {
    exit 0
}

# main/impl/* 등 코드 브랜치에서 docs/plan/ 또는 docs/archive/ 포함 시 경고
$planFiles = $staged | Where-Object { $_ -match "^docs/(plan|archive)/" }

if ($planFiles) {
    Write-Warning "⚠️  [pre-commit hook] 코드 브랜치($branch)에서 계획서/아카이브 커밋 감지"
    Write-Warning "    감지된 파일:"
    $planFiles | ForEach-Object { Write-Warning "      - $_" }
    Write-Warning "    계획서 수정은 '.worktrees/plans' 워크트리에서 수행하세요."
    Write-Warning "    (현재는 경고 모드 — 커밋이 차단되지 않습니다)"
}

exit 0
