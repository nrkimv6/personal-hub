$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    $repoRootText = $repoRoot.Path
    $worktreesMarker = "{0}.worktrees{0}" -f [System.IO.Path]::DirectorySeparatorChar
    $markerIndex = $repoRootText.IndexOf($worktreesMarker, [System.StringComparison]::OrdinalIgnoreCase)
    if ($markerIndex -ge 0) {
        $mainRoot = $repoRootText.Substring(0, $markerIndex)
        $fallbackPython = Join-Path $mainRoot ".venv\Scripts\python.exe"
        if (Test-Path $fallbackPython) {
            $pythonExe = $fallbackPython
        }
    }
}

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python 가상환경을 찾지 못했습니다: $pythonExe"
    exit 1
}

& $pythonExe -m app.cli.tracking_update @args
exit $LASTEXITCODE
