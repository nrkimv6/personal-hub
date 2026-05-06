param(
    [string]$RepoRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$installer = "D:\work\project\service\wtools\common\tools\enable-post-merge-dirty-check.ps1"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "missing wtools post-merge dirty installer: $installer"
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Join-Path $PSScriptRoot "..\.."
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
& $installer -RepoRoot $resolvedRepoRoot
