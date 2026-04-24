# archive-search.ps1 — LLM/사람용 archive 검색 단일 진입점. 내부 DB/파일 구현은 숨김.
#
# 사용법:
#   .\scripts\archive-search.ps1 --q watchdog
#   .\scripts\archive-search.ps1 --q watchdog --Tags worker,api --Limit 5
#   .\scripts\archive-search.ps1 --q watchdog --Offline
#   .\scripts\archive-search.ps1 --q watchdog --Content --Format json
#
# EXIT CODES: 0=결과있음, 1=결과없음, 2=에러

param(
    [string]$Q = "",
    [string]$Tags = "",
    [string]$DateFrom = "",
    [string]$DateTo = "",
    [switch]$Content,
    [switch]$Offline,
    [string]$Format = "text",
    [int]$Limit = 20
)

$pythonExe = "D:\work\project\tools\monitor-page\.venv\Scripts\python.exe"
$scriptPath = Join-Path $PSScriptRoot "archive_search.py"

$params = @()

if ($Q) { $params += "--q"; $params += $Q }
if ($Tags) { $params += "--tags"; $params += $Tags }
if ($DateFrom) { $params += "--date-from"; $params += $DateFrom }
if ($DateTo) { $params += "--date-to"; $params += $DateTo }
if ($Content) { $params += "--content" }
if ($Offline) { $params += "--offline" }
if ($Format) { $params += "--format"; $params += $Format }
if ($Limit) { $params += "--limit"; $params += $Limit }

& $pythonExe $scriptPath @params

exit $LASTEXITCODE
