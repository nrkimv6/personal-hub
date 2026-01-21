# Script to replace legacy .btn CSS classes with <Button> Svelte component
# Run this from the project root: D:\work\project\tools\monitor-page

$ErrorActionPreference = "Stop"

# Files already processed (skip these)
$processedFiles = @(
    "frontend\src\lib\components\events\EventFilterPanel.svelte",
    "frontend\src\lib\components\events\EventFormModal.svelte",
    "frontend\src\lib\components\events\EventFeedViewerModal.svelte",
    "frontend\src\lib\components\instagram\TagManager.svelte",
    "frontend\src\lib\components\InstagramCrawlSettings.svelte"
)

# Files to process
$filesToProcess = @(
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

function Add-ButtonImport {
    param([string]$Content)

    if ($Content -match "import \{ Button \} from '\`$lib/components/ui'") {
        return $Content
    }

    # Find last import and add Button import after it
    if ($Content -match "(?sm)(.*import [^;]+;)(\s+)(let|const|interface|type|export)") {
        $beforeLastImport = $matches[1]
        $whitespace = $matches[2]
        $afterImports = $matches[3]

        $newImport = "`timport { Button } from '`$lib/components/ui';"
        return $Content -replace [regex]::Escape("$beforeLastImport$whitespace$afterImports"), "$beforeLastImport`n$newImport$whitespace$afterImports"
    }

    return $Content
}

function Replace-BtnWithButton {
    param([string]$FilePath)

    Write-Host "Processing: $FilePath" -ForegroundColor Cyan

    if (-not (Test-Path $FilePath)) {
        Write-Host "  File not found!" -ForegroundColor Red
        return
    }

    $content = Get-Content -Path $FilePath -Raw -Encoding UTF8
    $originalContent = $content

    # Add import if missing
    $content = Add-ButtonImport -Content $content

    # Replace button elements - careful pattern matching to avoid issues
    # Pattern: <button ... class="btn btn-XXX btn-YYY" ... onclick={...}>...</button>

    # btn-primary btn-sm
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-primary\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="primary" size="sm"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-primary\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="primary" size="sm"$3on:click={$4}$5>'

    # btn-secondary btn-sm
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-secondary\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="secondary" size="sm"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-secondary\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="secondary" size="sm"$3on:click={$4}$5>'

    # btn-danger btn-sm
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-danger\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="destructive" size="sm"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-danger\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="destructive" size="sm"$3on:click={$4}$5>'

    # btn-success btn-sm
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-success\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="success" size="sm"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-success\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="success" size="sm"$3on:click={$4}$5>'

    # btn-outline btn-sm
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-outline\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="outline" size="sm"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-outline\b[^"]*\bbtn-sm\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="outline" size="sm"$3on:click={$4}$5>'

    # Regular buttons without size
    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-primary\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="primary"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-primary\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="primary"$3on:click={$4}$5>'

    $content = $content -replace '<button\s+([^>]*)onclick=\{([^\}]+)\}([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-secondary\b[^"]*)"([^>]*)>', '<Button $1on:click={$2}$3variant="secondary"$5>'
    $content = $content -replace '<button\s+([^>]*)class="([^"]*\bbtn\b[^"]*\bbtn-secondary\b[^"]*)"([^>]*)onclick=\{([^\}]+)\}([^>]*)>', '<Button $1variant="secondary"$3on:click={$4}$5>'

    # onclick → on:click for buttons converted above
    $content = $content -replace '(<Button[^>]*)onclick=', '$1on:click='

    # Replace </button> with </Button>
    $content = $content -replace '</button>', '</Button>'

    if ($content -ne $originalContent) {
        Set-Content -Path $FilePath -Value $content -Encoding UTF8 -NoNewline
        Write-Host "  Updated successfully!" -ForegroundColor Green
    } else {
        Write-Host "  No changes needed" -ForegroundColor Yellow
    }
}

Write-Host "Starting .btn class replacement..." -ForegroundColor Green
Write-Host ""

foreach ($file in $filesToProcess) {
    $fullPath = Join-Path (Get-Location) $file
    Replace-BtnWithButton -FilePath $fullPath
}

Write-Host ""
Write-Host "All files processed!" -ForegroundColor Green
Write-Host ""
Write-Host "Please verify the changes and test the components." -ForegroundColor Cyan
