<#
.SYNOPSIS
    Best-effort post-write plan commit hook.

.DESCRIPTION
    Reads hook input from stdin or surface-specific environment variables,
    detects writes to docs/plan markdown files, and commits only that plan file
    through the shared commit wrapper. The hook is intentionally non-blocking:
    all paths exit 0, with failures reported on stderr.
#>

[CmdletBinding()]
param(
    [ValidateSet("claude", "codex", "gemini")]
    [string]$Surface = "codex"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Write-HookError {
    param([string]$Message)
    [Console]::Error.WriteLine("plan-write-postcommit: $Message")
}

function Read-HookInput {
    $candidates = New-Object System.Collections.Generic.List[string]

    $envNames = @(
        "PLAN_WRITE_POSTCOMMIT_FILE_PATH",
        "PLAN_WRITE_FILE_PATH",
        "CLAUDE_FILE_PATH",
        "CODEX_FILE_PATH",
        "GEMINI_FILE_PATH",
        "CLAUDE_TOOL_INPUT",
        "CODEX_TOOL_INPUT",
        "GEMINI_TOOL_INPUT",
        "CLAUDE_HOOK_INPUT",
        "CODEX_HOOK_INPUT",
        "GEMINI_HOOK_INPUT"
    )

    foreach ($name in $envNames) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $candidates.Add($value)
        }
    }

    try {
        if (-not [Console]::IsInputRedirected) {
            return @($candidates)
        }
        $stdin = [Console]::In.ReadToEnd()
        if (-not [string]::IsNullOrWhiteSpace($stdin)) {
            $candidates.Add($stdin)
        }
    } catch {
        Write-HookError "failed to read stdin: $($_.Exception.Message)"
    }

    return @($candidates)
}

function Find-FilePathInObject {
    param([object]$Value)

    if ($null -eq $Value) {
        return ""
    }

    if ($Value -is [string]) {
        $trimmed = $Value.Trim()
        if ($trimmed -match '(^|[\\/])(\.worktrees[\\/]plans[\\/])?docs[\\/]plan[\\/].+\.md$') {
            return $trimmed
        }
        if ($trimmed -match '\.md$') {
            return $trimmed
        }
        return ""
    }

    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in @("file_path", "filePath", "path", "file", "filepath")) {
            if ($Value.Contains($key)) {
                $found = Find-FilePathInObject -Value $Value[$key]
                if ($found) { return $found }
            }
        }
        foreach ($entry in $Value.GetEnumerator()) {
            $found = Find-FilePathInObject -Value $entry.Value
            if ($found) { return $found }
        }
        return ""
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        foreach ($item in $Value) {
            $found = Find-FilePathInObject -Value $item
            if ($found) { return $found }
        }
        return ""
    }

    $properties = @($Value.PSObject.Properties)
    foreach ($name in @("tool_input", "input", "params", "arguments")) {
        $property = @($properties | Where-Object { $_.Name -eq $name } | Select-Object -First 1)
        if ($property.Count -gt 0) {
            $found = Find-FilePathInObject -Value $property[0].Value
            if ($found) { return $found }
        }
    }
    foreach ($name in @("file_path", "filePath", "path", "file", "filepath")) {
        $property = @($properties | Where-Object { $_.Name -eq $name } | Select-Object -First 1)
        if ($property.Count -gt 0) {
            $found = Find-FilePathInObject -Value $property[0].Value
            if ($found) { return $found }
        }
    }
    foreach ($property in $properties) {
        $found = Find-FilePathInObject -Value $property.Value
        if ($found) { return $found }
    }

    return ""
}

function Resolve-HookFilePath {
    foreach ($candidate in Read-HookInput) {
        $trimmed = [string]$candidate
        $trimmed = $trimmed.Trim()
        if (-not $trimmed) {
            continue
        }

        try {
            if ($trimmed.StartsWith("{") -or $trimmed.StartsWith("[")) {
                $json = $trimmed | ConvertFrom-Json -ErrorAction Stop
                $found = Find-FilePathInObject -Value $json
                if ($found) { return $found }
            }
        } catch {
            Write-HookError "failed to parse JSON input: $($_.Exception.Message)"
        }

        $foundPlain = Find-FilePathInObject -Value $trimmed
        if ($foundPlain) { return $foundPlain }
    }

    return ""
}

function Test-PlanPath {
    param([string]$Path)
    if (-not $Path) { return $false }
    $normalized = $Path.Replace('\', '/')
    return ($normalized -match '(^|/)(\.worktrees/plans/)?docs/plan/[^/]+\.md$')
}

function Resolve-CommitTarget {
    param([string]$Path)

    $candidate = $Path.Trim().Trim('"')
    if ([System.IO.Path]::IsPathRooted($candidate)) {
        $fullPath = [System.IO.Path]::GetFullPath($candidate)
    } else {
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $candidate))
    }

    $normalizedFull = $fullPath.Replace('\', '/')
    $marker = "/.worktrees/plans/docs/plan/"
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    $markerIndex = $normalizedFull.IndexOf($marker, $comparison)
    if ($markerIndex -ge 0) {
        $root = $fullPath.Substring(0, $markerIndex + "/.worktrees/plans".Length).Replace('/', '\')
        return [PSCustomObject]@{
            Root = [System.IO.Path]::GetFullPath($root)
            RelativePath = ("docs/plan/" + [System.IO.Path]::GetFileName($fullPath)).Replace('\', '/')
            FullPath = $fullPath
        }
    }

    $dir = Split-Path -Parent $fullPath
    while ($dir) {
        if (Test-Path -LiteralPath (Join-Path $dir ".git")) {
            $root = [System.IO.Path]::GetFullPath($dir)
            $rootTrimmed = $root.TrimEnd('\', '/')
            if ($fullPath.StartsWith($rootTrimmed + [System.IO.Path]::DirectorySeparatorChar, $comparison)) {
                $relative = $fullPath.Substring($rootTrimmed.Length + 1).Replace('\', '/')
                return [PSCustomObject]@{
                    Root = $root
                    RelativePath = $relative
                    FullPath = $fullPath
                }
            }
        }
        $parent = Split-Path -Parent $dir
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }

    throw "could not resolve git commit root for $Path"
}

function Invoke-PlanCommit {
    param([object]$Target)

    if (-not (Test-Path -LiteralPath $Target.Root -PathType Container)) {
        throw "commit root does not exist: $($Target.Root)"
    }

    $commitScript = $env:WTOOLS_COMMIT_PS1
    if (-not $commitScript) {
        $commitScript = "D:\work\project\tools\common\commit.ps1"
    }
    if (-not (Test-Path -LiteralPath $commitScript -PathType Leaf)) {
        throw "commit.ps1 not found: $commitScript"
    }
    $lockScript = Join-Path (Split-Path -Parent $PSScriptRoot) "plan-docs-lock.ps1"
    if (-not (Test-Path -LiteralPath $lockScript -PathType Leaf)) {
        throw "plan-docs-lock.ps1 not found: $lockScript"
    }

    $message = "docs: plan " + [System.IO.Path]::GetFileNameWithoutExtension($Target.FullPath)
    $stdoutFile = ""
    $stderrFile = ""
    $oldTargetRoot = $env:PLAN_DOCS_LOCK_TARGET_ROOT
    $oldCommitScript = $env:PLAN_DOCS_LOCK_COMMIT_SCRIPT
    $oldRelativePath = $env:PLAN_DOCS_LOCK_RELATIVE_PATH
    $oldMessage = $env:PLAN_DOCS_LOCK_MESSAGE
    $oldStdout = $env:PLAN_DOCS_LOCK_STDOUT_FILE
    $oldStderr = $env:PLAN_DOCS_LOCK_STDERR_FILE
    try {
        $stdoutFile = [System.IO.Path]::GetTempFileName()
        $stderrFile = [System.IO.Path]::GetTempFileName()
        $env:PLAN_DOCS_LOCK_TARGET_ROOT = $Target.Root
        $env:PLAN_DOCS_LOCK_COMMIT_SCRIPT = $commitScript
        $env:PLAN_DOCS_LOCK_RELATIVE_PATH = $Target.RelativePath
        $env:PLAN_DOCS_LOCK_MESSAGE = $message
        $env:PLAN_DOCS_LOCK_STDOUT_FILE = $stdoutFile
        $env:PLAN_DOCS_LOCK_STDERR_FILE = $stderrFile

        $lockCommand = @"
& '$lockScript' -RepoRoot `$env:PLAN_DOCS_LOCK_TARGET_ROOT -Operation 'hook-commit' -ScriptBlock {
    Push-Location `$env:PLAN_DOCS_LOCK_TARGET_ROOT
    try {
        & `$env:PLAN_DOCS_LOCK_COMMIT_SCRIPT -Files @(`$env:PLAN_DOCS_LOCK_RELATIVE_PATH) -Message `$env:PLAN_DOCS_LOCK_MESSAGE 1>`$env:PLAN_DOCS_LOCK_STDOUT_FILE 2>`$env:PLAN_DOCS_LOCK_STDERR_FILE
        if (`$LASTEXITCODE -ne 0) {
            throw "commit.ps1 failed with exit code `$LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}
"@
        $lockOutput = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $lockCommand 2>&1)
        $lockExitCode = $LASTEXITCODE
        if ($lockExitCode -eq 7) {
            Write-HookError "PLAN_DOCS_LOCK_TIMEOUT: $($lockOutput -join ' ')"
            return
        }
        if ($lockExitCode -ne 0) {
            $stderr = Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue
            $stdout = Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue
            $details = (($stderr + "`n" + $stdout + "`n" + ($lockOutput -join "`n")).Trim())
            if ($details) {
                Write-HookError $details
            }
            throw "plan-docs-lock failed with exit code $lockExitCode"
        }
        $sha = (& git -C $Target.Root rev-parse --short HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $sha) {
            $shaText = [string](@($sha) | Select-Object -First 1)
            Write-Output ("plan_commit: {0}" -f $shaText.Trim())
        } else {
            Write-Output "plan_commit:unknown"
        }
    } finally {
        if ($stdoutFile -and (Test-Path -LiteralPath $stdoutFile)) {
            Remove-Item -LiteralPath $stdoutFile -Force -ErrorAction SilentlyContinue
        }
        if ($stderrFile -and (Test-Path -LiteralPath $stderrFile)) {
            Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
        }
        $env:PLAN_DOCS_LOCK_TARGET_ROOT = $oldTargetRoot
        $env:PLAN_DOCS_LOCK_COMMIT_SCRIPT = $oldCommitScript
        $env:PLAN_DOCS_LOCK_RELATIVE_PATH = $oldRelativePath
        $env:PLAN_DOCS_LOCK_MESSAGE = $oldMessage
        $env:PLAN_DOCS_LOCK_STDOUT_FILE = $oldStdout
        $env:PLAN_DOCS_LOCK_STDERR_FILE = $oldStderr
    }
}

try {
    $filePath = Resolve-HookFilePath
    if (-not (Test-PlanPath -Path $filePath)) {
        exit 0
    }

    $target = Resolve-CommitTarget -Path $filePath
    if (-not (Test-PlanPath -Path $target.RelativePath)) {
        exit 0
    }
    Invoke-PlanCommit -Target $target
} catch {
    Write-HookError $_.Exception.Message
}

exit 0
