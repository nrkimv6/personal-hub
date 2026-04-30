$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python 가상환경을 찾지 못했습니다: $pythonExe"
    exit 1
}

& $pythonExe -m app.cli.tracking_add @args
exit $LASTEXITCODE
