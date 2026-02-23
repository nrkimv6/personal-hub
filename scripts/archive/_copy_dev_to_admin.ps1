$src = "D:\work\project\tools\monitor-page\logs\dev"
$dst = "D:\work\project\tools\monitor-page\logs\admin"
Write-Host "Copying from: $src"
Write-Host "Copying to: $dst"
if (-not (Test-Path $dst)) {
    New-Item -ItemType Directory -Path $dst | Out-Null
}
$files = Get-ChildItem -Path $src -Recurse -File -ErrorAction SilentlyContinue
$count = 0
foreach ($file in $files) {
    $rel = $file.FullName.Substring($src.Length).TrimStart('\')
    $target = Join-Path $dst $rel
    $targetDir = Split-Path $target -Parent
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    try {
        Copy-Item -Path $file.FullName -Destination $target -Force
        $count++
    } catch {
        # skip locked files
    }
}
Write-Host "Copied $count files from dev to admin"
