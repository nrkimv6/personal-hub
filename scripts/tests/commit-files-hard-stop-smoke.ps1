param(
    [string]$CommitScript = "D:\work\project\tools\common\commit.ps1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail {
    param([string]$Message)

    Write-Error $Message
    exit 1
}

function Invoke-CommitScript {
    param([string[]]$Arguments)

    $output = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $CommitScript @Arguments 2>&1)
    [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = ($output -join "`n")
    }
}

function New-FixtureRepo {
    $root = Join-Path ([System.IO.Path]::GetTempPath()) ("commit-files-hard-stop-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $root | Out-Null
    git -C $root init | Out-Null
    git -C $root config user.email "commit-smoke@example.invalid"
    git -C $root config user.name "Commit Smoke"

    Set-Content -LiteralPath (Join-Path $root "base.txt") -Value "base" -Encoding UTF8
    git -C $root add -- base.txt
    Push-Location $root
    try {
        $initial = Invoke-CommitScript -Arguments @("test: initial")
        if ($initial.ExitCode -ne 0) {
            Fail "initial commit failed: $($initial.Output)"
        }
    }
    finally {
        Pop-Location
    }

    return $root
}

if (-not (Test-Path -LiteralPath $CommitScript -PathType Leaf)) {
    Fail "commit script not found: $CommitScript"
}

$fixtures = New-Object System.Collections.Generic.List[string]

try {
    $blockedRepo = New-FixtureRepo
    $fixtures.Add($blockedRepo)

    Set-Content -LiteralPath (Join-Path $blockedRepo "staged.md") -Value "staged" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $blockedRepo "target.md") -Value "target" -Encoding UTF8
    git -C $blockedRepo add -- staged.md
    $beforeCached = @((git -C $blockedRepo diff --cached --name-status) | Sort-Object)
    $beforeStatus = @((git -C $blockedRepo status --short) | Sort-Object)

    Push-Location $blockedRepo
    try {
        $blocked = Invoke-CommitScript -Arguments @("-Message", "test: scoped blocked", "-Files", "target.md")
    }
    finally {
        Pop-Location
    }

    if ($blocked.ExitCode -eq 0) {
        Fail "-Files with preexisting staged changes unexpectedly succeeded"
    }
    if ($blocked.Output -notmatch "-Files cannot run with existing staged changes") {
        Fail "missing hard-stop reason in output: $($blocked.Output)"
    }
    if ($blocked.Output -notmatch "staged\.md") {
        Fail "missing staged path in output: $($blocked.Output)"
    }

    $afterCached = @((git -C $blockedRepo diff --cached --name-status) | Sort-Object)
    $afterStatus = @((git -C $blockedRepo status --short) | Sort-Object)
    if (($beforeCached -join "`n") -ne ($afterCached -join "`n")) {
        Fail "cached index changed after blocked -Files call. before=[$($beforeCached -join ', ')] after=[$($afterCached -join ', ')]"
    }
    if (($beforeStatus -join "`n") -ne ($afterStatus -join "`n")) {
        Fail "worktree status changed after blocked -Files call. before=[$($beforeStatus -join ', ')] after=[$($afterStatus -join ', ')]"
    }
    if (@(git -C $blockedRepo diff --cached --name-only).Contains("target.md")) {
        Fail "target.md was staged despite hard-stop"
    }

    $scopedRepo = New-FixtureRepo
    $fixtures.Add($scopedRepo)
    Set-Content -LiteralPath (Join-Path $scopedRepo "target.md") -Value "target" -Encoding UTF8
    Push-Location $scopedRepo
    try {
        $scoped = Invoke-CommitScript -Arguments @("-Message", "test: scoped commit", "-Files", "target.md")
    }
    finally {
        Pop-Location
    }
    if ($scoped.ExitCode -ne 0) {
        Fail "-Files with empty index failed: $($scoped.Output)"
    }
    git -C $scopedRepo diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        Fail "staged changes remain after successful -Files commit"
    }
    $scopedSubject = git -C $scopedRepo log -1 --pretty=%s
    if ($scopedSubject -ne "test: scoped commit") {
        Fail "unexpected scoped commit subject: $scopedSubject"
    }

    $generalRepo = New-FixtureRepo
    $fixtures.Add($generalRepo)
    Set-Content -LiteralPath (Join-Path $generalRepo "general.md") -Value "general" -Encoding UTF8
    git -C $generalRepo add -- general.md
    Push-Location $generalRepo
    try {
        $general = Invoke-CommitScript -Arguments @("test: general staged commit")
    }
    finally {
        Pop-Location
    }
    if ($general.ExitCode -ne 0) {
        Fail "general non--Files commit failed: $($general.Output)"
    }
    $generalSubject = git -C $generalRepo log -1 --pretty=%s
    if ($generalSubject -ne "test: general staged commit") {
        Fail "unexpected general commit subject: $generalSubject"
    }

    Write-Host "commit-files hard-stop smoke passed"
}
finally {
    foreach ($fixture in $fixtures) {
        if (Test-Path -LiteralPath $fixture) {
            Remove-Item -LiteralPath $fixture -Recurse -Force
        }
    }
}
