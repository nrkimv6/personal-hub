"""Source contract tests for archive manual analyze ownership."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_plan_records_api_exposes_manual_analyze_wrappers():
    source = (ROOT / "frontend/src/lib/api/plan-records.ts").read_text(encoding="utf-8")

    assert "PlanArchiveAnalyzeResponse" in source
    assert "analyzeRecord" in source
    assert "/records/${recordId}/analyze" in source
    assert "analyzeDryRun" in source


def test_archive_tab_does_not_expose_manual_analyze_controls():
    tab_source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")
    detail_source = (
        ROOT / "frontend/src/routes/plans/archive-tab/ArchiveRecordDetailPanel.svelte"
    ).read_text(encoding="utf-8")
    combined = f"{tab_source}\n{detail_source}"

    assert "runManualAnalyze(" not in combined
    assert "analyzeRecord(" not in combined
    assert "Preview는 DB 저장 없음" not in combined
    assert "DB 저장" not in combined


def test_archive_tab_does_not_render_manual_analyze_result_fields():
    tab_source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")
    detail_source = (
        ROOT / "frontend/src/routes/plans/archive-tab/ArchiveRecordDetailPanel.svelte"
    ).read_text(encoding="utf-8")
    combined = f"{tab_source}\n{detail_source}"

    for field in ("category", "tags", "summary", "intent", "scope"):
        assert f"analyzeResult.result.{field}" not in combined


def test_archive_retention_fields_are_visible():
    api_source = (ROOT / "frontend/src/lib/api/plan-records.ts").read_text(encoding="utf-8")
    tab_source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")
    viewer_source = (ROOT / "frontend/src/routes/plans/PlanViewer.svelte").read_text(encoding="utf-8")

    assert "file_delete_after" in api_source
    assert "file_removed_at" in api_source
    assert "file_delete_after" in tab_source
    assert "삭제 예정" in tab_source
    assert "getContent" in viewer_source
