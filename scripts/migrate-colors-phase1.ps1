# Phase 1: 안전한 1:1 색상 클래스 자동 변환
# 그레이스케일, 테두리, 호버 상태 등 확실한 매핑만 처리

$mappings = @{
    # Gray text - foreground
    'text-gray-900' = 'text-foreground'
    'text-gray-800' = 'text-foreground'
    'text-gray-700' = 'text-foreground'

    # Gray text - muted
    'text-gray-600' = 'text-muted-foreground'
    'text-gray-500' = 'text-muted-foreground'
    'text-gray-400' = 'text-muted-foreground'

    # Gray background
    'bg-gray-100' = 'bg-muted'
    'bg-gray-50' = 'bg-background'
    'bg-gray-200' = 'bg-secondary'

    # White backgrounds (context-aware는 Phase 2에서)
    'bg-white border' = 'bg-card border'

    # Borders
    'border-gray-200' = 'border-border'
    'border-gray-300' = 'border-border'
    'border-gray-100' = 'border-border'
    'divide-gray-200' = 'divide-border'
    'divide-gray-100' = 'divide-border'

    # Hover states - background
    'hover:bg-gray-100' = 'hover:bg-muted'
    'hover:bg-gray-50' = 'hover:bg-muted'
    'hover:bg-gray-200' = 'hover:bg-secondary'

    # Hover states - text
    'hover:text-gray-700' = 'hover:text-foreground'
    'hover:text-gray-900' = 'hover:text-foreground'
    'hover:text-gray-600' = 'hover:text-muted-foreground'
}

$targetDir = "D:\work\project\tools\monitor-page\frontend\src"
$files = Get-ChildItem -Path $targetDir -Recurse -Include "*.svelte", "*.ts" | Where-Object {
    $_.FullName -notlike "*node_modules*" -and
    $_.FullName -notlike "*.test.*"
}

$totalFiles = 0
$totalReplacements = 0

Write-Host "🎨 Phase 1: 안전한 색상 클래스 자동 변환 시작..." -ForegroundColor Cyan
Write-Host "대상 파일: $($files.Count)개`n" -ForegroundColor Yellow

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $content) { continue }

    $modified = $false
    $fileReplacements = 0

    foreach ($old in $mappings.Keys) {
        $new = $mappings[$old]
        $pattern = [regex]::Escape($old)

        if ($content -match $pattern) {
            $matchCount = ([regex]::Matches($content, $pattern)).Count
            $content = $content -replace $pattern, $new
            $modified = $true
            $fileReplacements += $matchCount
        }
    }

    if ($modified) {
        Set-Content -Path $file.FullName -Value $content -NoNewline -Encoding UTF8
        $totalFiles++
        $totalReplacements += $fileReplacements

        $relativePath = $file.FullName.Replace("$targetDir\", "")
        Write-Host "  ✓ $relativePath ($fileReplacements 교체)" -ForegroundColor Green
    }
}

Write-Host "`n✅ Phase 1 완료!" -ForegroundColor Green
Write-Host "  - 수정된 파일: $totalFiles 개" -ForegroundColor Cyan
Write-Host "  - 총 교체 수: $totalReplacements 개" -ForegroundColor Cyan
Write-Host "`n다음 단계: Phase 2 (시맨틱 색상 수동 변환)" -ForegroundColor Yellow
