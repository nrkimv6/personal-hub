# Script to replace legacy .btn CSS classes with <Button> Svelte component
# Usage: Run from project root

$files = @(
    "frontend\src\lib\components\instagram\TagManager.svelte",
    "frontend\src\lib\components\InstagramCrawlSettings.svelte",
    "frontend\src\lib\components\InstagramCrawlHistory.svelte",
    "frontend\src\lib\components\LLMPerformance.svelte",
    "frontend\src\lib\components\events\CrawlScheduleTab.svelte",
    "frontend\src\lib\components\events\CrawlTab.svelte",
    "frontend\src\lib\components\businesses\BusinessManager.svelte",
    "frontend\src\lib\components\instagram\FeedCard.svelte",
    "frontend\src\lib\components\SnipeHistory.svelte",
    "frontend\src\lib\components\NotificationSettings.svelte",
    "frontend\src\lib\components\SchedulerSettings.svelte",
    "frontend\src\lib\components\MonitoringHistory.svelte",
    "frontend\src\lib\components\schedules\AutoBookingList.svelte"
)

$projectRoot = "D:\work\project\tools\monitor-page"

function Replace-BtnClasses {
    param(
        [string]$FilePath
    )

    Write-Host "Processing: $FilePath" -ForegroundColor Cyan

    $content = Get-Content -Path $FilePath -Raw -Encoding UTF8

    # Check if Button component is already imported
    if ($content -notmatch "import \{ Button \} from '\$lib/components/ui'") {
        # Find the last import statement
        if ($content -match "(?s)(import .+? from .+?;)(\s+)(interface|let|const|type|export)") {
            $lastImport = $matches[1]
            $whitespace = $matches[2]
            $nextLine = $matches[3]

            $newImport = "$lastImport`n`timport { Button } from '`$lib/components/ui';$whitespace$nextLine"
            $content = $content -replace [regex]::Escape("$lastImport$whitespace$nextLine"), $newImport

            Write-Host "  Added Button import" -ForegroundColor Green
        }
    }

    # Replace button elements with Button component
    # Pattern 1: <button ... class="btn btn-primary btn-sm" ...>...</button>
    $content = $content -replace '<button\s+onclick=\{([^\}]+)\}\s+class="btn btn-primary btn-sm">', '<Button variant="primary" size="sm" on:click={$1}>'
    $content = $content -replace '<button\s+onclick=\{([^\}]+)\}\s+disabled=\{([^\}]+)\}\s+class="btn btn-primary btn-sm[^"]*">', '<Button variant="primary" size="sm" on:click={$1} disabled={$2}>'
    $content = $content -replace '<button\s+onclick=\{([^\}]+)\}\s+class="btn btn-secondary btn-sm">', '<Button variant="secondary" size="sm" on:click={$1}>'
    $content = $content -replace '<button\s+onclick=\{([^\}]+)\}\s+class="btn btn-primary">', '<Button variant="primary" on:click={$1}>'
    $content = $content -replace '<button\s+onclick=\{([^\}]+)\}\s+class="btn btn-secondary">', '<Button variant="secondary" on:click={$1}>'
    $content = $content -replace '</button>', '</Button>'

    # Save the file
    Set-Content -Path $FilePath -Value $content -Encoding UTF8 -NoNewline

    Write-Host "  Completed: $FilePath" -ForegroundColor Green
}

foreach ($file in $files) {
    $fullPath = Join-Path $projectRoot $file
    if (Test-Path $fullPath) {
        Replace-BtnClasses -FilePath $fullPath
    } else {
        Write-Host "File not found: $fullPath" -ForegroundColor Red
    }
}

Write-Host "`nAll files processed!" -ForegroundColor Green
