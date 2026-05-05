"""Source contract tests for ArchiveTab manual analyze controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_plan_records_api_exposes_manual_analyze_wrappers():
    source = (ROOT / "frontend/src/lib/api/plan-records.ts").read_text(encoding="utf-8")

    assert "PlanArchiveAnalyzeResponse" in source
    assert "analyzeRecord" in source
    assert "/records/${recordId}/analyze" in source
    assert "analyzeDryRun" in source


def test_archive_tab_exposes_preview_apply_and_no_save_notice():
    source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")

    assert "runManualAnalyze('preview')" in source
    assert "runManualAnalyze('apply')" in source
    assert "Preview는 DB 저장 없음" in source
    assert "DB 저장" in source


def test_archive_tab_renders_key_result_fields():
    source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")

    for field in ("category", "tags", "summary", "intent", "scope"):
        assert f"analyzeResult.result.{field}" in source


def test_archive_retention_fields_are_visible():
    api_source = (ROOT / "frontend/src/lib/api/plan-records.ts").read_text(encoding="utf-8")
    tab_source = (ROOT / "frontend/src/routes/plans/ArchiveTab.svelte").read_text(encoding="utf-8")
    viewer_source = (ROOT / "frontend/src/routes/plans/PlanViewer.svelte").read_text(encoding="utf-8")

    assert "file_delete_after" in api_source
    assert "file_removed_at" in api_source
    assert "file_retention_due" in tab_source
    assert "삭제 예정" in tab_source
    assert "getContent" in viewer_source
