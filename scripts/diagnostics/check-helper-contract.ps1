param(
    [string]$RepoRoot,
    [string]$WtoolsToolsRoot = "D:\work\project\service\wtools\common\tools",
    [string]$LegacyCommonRoot = "D:\work\project\tools\common",
    [switch]$Json
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$repoLocalToolsRoot = Join-Path $RepoRoot "common\tools"
$mirrorRoots = @(".agents", ".claude", ".agent", ".gemini")
$extensions = "ps1|sh|py"

function Convert-ToRepoRelativePath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath.Substring($RepoRoot.Length).TrimStart("\", "/")
    }
    return $fullPath
}

function Normalize-HelperRelativePath {
    param([string]$Path)

    return ($Path -replace "/", "\").TrimStart("\", "/")
}

function Add-Mention {
    param(
        [hashtable]$Inventory,
        [string]$Surface,
        [string]$RelativePath,
        [string]$MentionText,
        [string]$SourceFile,
        [int]$Line
    )

    $normalizedRelative = Normalize-HelperRelativePath $RelativePath
    $key = "$Surface|$normalizedRelative".ToLowerInvariant()
    if (-not $Inventory.ContainsKey($key)) {
        $Inventory[$key] = [pscustomobject]@{
            surface = $Surface
            helper = $normalizedRelative
            mention_count = 0
            mentions = New-Object System.Collections.Generic.List[object]
        }
    }

    $Inventory[$key].mention_count += 1
    $Inventory[$key].mentions.Add([pscustomobject]@{
        file = Convert-ToRepoRelativePath $SourceFile
        line = $Line
        text = $MentionText
    }) | Out-Null
}

function Resolve-InventoryItem {
    param([pscustomobject]$Item)

    if ($Item.surface -eq "legacy-common") {
        $path = Join-Path $LegacyCommonRoot $Item.helper
        $exists = Test-Path -LiteralPath $path -PathType Leaf
        $status = if ($exists) { "legacy-common" } else { "missing" }
        return [pscustomobject]@{
            helper = $Item.helper
            surface = $Item.surface
            status = $status
            resolved_path = if ($exists) { $path } else { $null }
            repo_local_path = $null
            wtools_canonical_path = $null
            legacy_common_path = $path
            mention_count = $Item.mention_count
            mentions = $Item.mentions
        }
    }

    $repoLocalPath = Join-Path $repoLocalToolsRoot $Item.helper
    if (Test-Path -LiteralPath $repoLocalPath -PathType Leaf) {
        return [pscustomobject]@{
            helper = $Item.helper
            surface = $Item.surface
            status = "resolved"
            resolved_path = $repoLocalPath
            repo_local_path = $repoLocalPath
            wtools_canonical_path = $null
            legacy_common_path = $null
            mention_count = $Item.mention_count
            mentions = $Item.mentions
        }
    }

    $wtoolsPath = Join-Path $WtoolsToolsRoot $Item.helper
    if (Test-Path -LiteralPath $wtoolsPath -PathType Leaf) {
        return [pscustomobject]@{
            helper = $Item.helper
            surface = $Item.surface
            status = "wtools-canonical"
            resolved_path = $wtoolsPath
            repo_local_path = $repoLocalPath
            wtools_canonical_path = $wtoolsPath
            legacy_common_path = $null
            mention_count = $Item.mention_count
            mentions = $Item.mentions
        }
    }

    return [pscustomobject]@{
        helper = $Item.helper
        surface = $Item.surface
        status = "missing"
        resolved_path = $null
        repo_local_path = $repoLocalPath
        wtools_canonical_path = $wtoolsPath
        legacy_common_path = $null
        mention_count = $Item.mention_count
        mentions = $Item.mentions
    }
}

$inventory = @{}
$commonToolsPattern = [regex]"(?i)(?:common[\\/]+tools[\\/]+)(?<path>[\w.\-\\/]+?\.(?:$extensions))"
$legacyPatterns = @(
    [regex]"(?i)D:[\\/]+work[\\/]+project[\\/]+tools[\\/]+common[\\/]+(?<path>[\w.\-\\/]+?\.(?:$extensions))",
    [regex]"(?i)/d/work/project/tools/common/(?<path>[\w.\-\\/]+?\.(?:$extensions))"
)

foreach ($mirrorRootName in $mirrorRoots) {
    $mirrorRoot = Join-Path $RepoRoot $mirrorRootName
    if (-not (Test-Path -LiteralPath $mirrorRoot -PathType Container)) {
        continue
    }

    $files = Get-ChildItem -LiteralPath $mirrorRoot -File -Recurse
    foreach ($file in $files) {
        $lineNumber = 0
        foreach ($line in Get-Content -LiteralPath $file.FullName) {
            $lineNumber += 1

            foreach ($match in $commonToolsPattern.Matches($line)) {
                Add-Mention `
                    -Inventory $inventory `
                    -Surface "common-tools" `
                    -RelativePath $match.Groups["path"].Value `
                    -MentionText $match.Value `
                    -SourceFile $file.FullName `
                    -Line $lineNumber
            }

            foreach ($pattern in $legacyPatterns) {
                foreach ($match in $pattern.Matches($line)) {
                    Add-Mention `
                        -Inventory $inventory `
                        -Surface "legacy-common" `
                        -RelativePath $match.Groups["path"].Value `
                        -MentionText $match.Value `
                        -SourceFile $file.FullName `
                        -Line $lineNumber
                }
            }
        }
    }
}

$items = @($inventory.Values | ForEach-Object { Resolve-InventoryItem $_ } | Sort-Object surface, helper)
$statusCounts = [ordered]@{
    resolved = 0
    "wtools-canonical" = 0
    "legacy-common" = 0
    missing = 0
}

foreach ($item in $items) {
    if (-not $statusCounts.Contains($item.status)) {
        $statusCounts[$item.status] = 0
    }
    $statusCounts[$item.status] += 1
}

$result = [pscustomobject]@{
    repo_root = $RepoRoot
    repo_local_tools_root = $repoLocalToolsRoot
    wtools_tools_root = $WtoolsToolsRoot
    legacy_common_root = $LegacyCommonRoot
    mirror_roots = $mirrorRoots
    generated_at = (Get-Date).ToString("o")
    summary = [pscustomobject]@{
        total = $items.Count
        status_counts = [pscustomobject]$statusCounts
        missing_count = $statusCounts["missing"]
    }
    items = $items
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host "helper contract inventory"
    Write-Host "repo root: $RepoRoot"
    Write-Host "repo-local common tools: $repoLocalToolsRoot"
    Write-Host "wtools canonical tools: $WtoolsToolsRoot"
    Write-Host "legacy common scripts: $LegacyCommonRoot"
    Write-Host ""
    $items |
        Select-Object status, surface, helper, resolved_path, mention_count |
        Format-Table -AutoSize
    Write-Host ""
    Write-Host ("summary: total={0}, resolved={1}, wtools-canonical={2}, legacy-common={3}, missing={4}" -f `
        $items.Count, `
        $statusCounts["resolved"], `
        $statusCounts["wtools-canonical"], `
        $statusCounts["legacy-common"], `
        $statusCounts["missing"])
}

if ($statusCounts["missing"] -gt 0) {
    exit 1
}

exit 0
