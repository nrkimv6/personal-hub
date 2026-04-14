# pre-commit-plans-warn.ps1
#
# 목적: active runner가 있는 동안만 mixed-scope staged commit을 차단한다.
# - runner가 없으면 manual commit은 pass-through
# - runner가 있으면 scripts/diagnostics/audit_mixed_scope_commits.py --staged 결과를 재사용해
#   plan/archive + code 혼합 스테이징만 block
#
# --no-verify 사용 절대 금지

$staged = git diff --cached --name-only 2>$null
$branch = git rev-parse --abbrev-ref HEAD 2>$null
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ownershipDir = Join-Path $projectRoot "logs\dev_runner\ownership"

# plans 브랜치이면 정상 — 경고 없음
if ($branch -eq "plans") {
    exit 0
}

# active runner snapshot이 없으면 manual commit은 그대로 허용
$activeSnapshots = @()
if (Test-Path $ownershipDir) {
    $activeSnapshots = @(Get-ChildItem -LiteralPath $ownershipDir -Filter "*.json" -File -ErrorAction SilentlyContinue)
}
if ($activeSnapshots.Count -eq 0) {
    exit 0
}

$planFiles = @($staged | Where-Object { $_ -match "^docs/(plan|archive)/" })
$codeFiles = @($staged | Where-Object { $_ -match "\.(py|ps1|svelte|ts|tsx|js|jsx|json|toml|yml|yaml)$" -and $_ -notmatch "^docs/" })
if ($planFiles.Count -eq 0 -or $codeFiles.Count -eq 0) {
    exit 0
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$auditScript = Join-Path $projectRoot "scripts\diagnostics\audit_mixed_scope_commits.py"

$report = & $python $auditScript --repo $projectRoot --staged --format json 2>&1
$auditExit = $LASTEXITCODE
if ($auditExit -eq 0) {
    exit 0
}

$findings = $null
try {
    if ($report) {
        $findings = $report | ConvertFrom-Json
    }
} catch {
    $findings = $null
}

Write-Warning "⚠️  [pre-commit hook] active runner ownership guard blocked a mixed-scope staged commit"
Write-Warning "    active snapshot:"
$activeSnapshots | ForEach-Object { Write-Warning "      - $($_.Name)" }
if ($findings) {
    @($findings) | ForEach-Object {
        Write-Warning "    [$($_.severity)] $($_.subject)"
        if ($_.linked_docs) {
            Write-Warning "      docs: $(@($_.linked_docs) -join ', ')"
        }
        if ($_.changed_files) {
            Write-Warning "      files: $(@($_.changed_files) -join ', ')"
        }
        if ($_.reason) {
            Write-Warning "      reason: $($_.reason)"
        }
    }
} elseif ($report) {
    Write-Warning "    audit output:"
    $report | ForEach-Object { Write-Warning "      $_" }
}

exit 1
