param(
    [string]$Upstream = "",
    [string]$Branch = ""
)

$ErrorActionPreference = "Stop"

$guard = Join-Path $PSScriptRoot "root-branch-guard.ps1"
if (-not (Test-Path -LiteralPath $guard)) {
    exit 0
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guard -Mode PreRebase
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Error "pre-rebase root guard failed (upstream=$Upstream, branch=$Branch)"
    exit $code
}

exit 0
