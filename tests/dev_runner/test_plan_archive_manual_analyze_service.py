"""Manual Plan Archive analyze service tests."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from unittest.mock import patch

from app.models.plan_record import PlanRecord
from app.modules.dev_runner.services.plan_archive_manual_analyze_service import (
    PlanArchiveManualAnalyzeService,
)


def _add_record(db, **kwargs) -> PlanRecord:
    record = PlanRecord(
        filename_hash=kwargs.pop("filename_hash", f"manual_analyze_{uuid4().hex}"),
        file_path=kwargs.pop("file_path", "/archive/2026-05-05_manual.md"),
        archived_at=kwargs.pop("archived_at", datetime.now()),
        status=kwargs.pop("status", "archived"),
        **kwargs,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_preview_uses_raw_content_and_does_not_mutate_record(test_db_session):
    """R: preview builds the real prompt from raw_content and leaves DB fields unchanged."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.2"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["feat"],
                "summary": "manual preview",
                "superseded_by": None,
                "intent": "check",
                "trigger": "infra",
                "scope": ["plan"],
            },
            "raw_response": '{"category":"infra"}',
        },
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.save_plan_archive_result"
    ) as mock_save:
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    test_db_session.refresh(record)
    assert result["success"] is True
    assert result["mode"] == "preview"
    assert result["provider"] == "codex"
    assert record.llm_processed_at is None
    assert record.category is None
    mock_save.assert_not_called()


def test_preview_falls_back_to_file_content(test_db_session, tmp_path):
    """R: file_path source is used when raw_content is empty."""
    archive_file = tmp_path / "2026-05-05_file-fallback.md"
    archive_file.write_text("# File fallback", encoding="utf-8")
    record = _add_record(test_db_session, file_path=str(archive_file), raw_content=None)

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("claude", "claude-opus-4-6"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={"success": True, "result": {"category": "docs"}, "raw_response": '{"category":"docs"}'},
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is True
    assert "MISSING_FIELDS" in " ".join(result["warnings"])


def test_preview_empty_content_returns_error(test_db_session):
    """E: empty raw_content and missing file returns EMPTY_PLAN_CONTENT."""
    record = _add_record(test_db_session, raw_content=None, file_path="/missing/archive.md")

    result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is False
    assert result["error"] == "EMPTY_PLAN_CONTENT"


def test_preview_parse_error_returns_raw_response(test_db_session):
    """E: non-JSON executor response is surfaced without saving."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.2"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={"success": True, "result": "not json", "raw_response": "not json"},
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.save_plan_archive_result"
    ) as mock_save:
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is False
    assert result["error"] == "PARSE_ERROR"
    assert result["raw_response"] == "not json"
    mock_save.assert_not_called()


def test_apply_success_saves_record_without_creating_request(test_db_session):
    """R: apply reuses save_plan_archive_result and does not enqueue the analyze request."""
    from app.modules.claude_worker.models.llm_request import LLMRequest

    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.2"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["feat"],
                "summary": "manual apply",
                "superseded_by": None,
            },
            "raw_response": '{"category":"infra"}',
        },
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="apply")

    test_db_session.refresh(record)
    assert result["success"] is True
    assert result["saved"] is True
    assert result["record_after"]["category"] == "infra"
    assert record.category == "infra"
    assert record.llm_processed_at is not None
    assert test_db_session.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").count() == 0


def test_apply_parse_error_does_not_save(test_db_session):
    """E: apply stops before save when JSON parsing fails."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.2"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={"success": True, "result": "not json", "raw_response": "not json"},
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.save_plan_archive_result"
    ) as mock_save:
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="apply")

    assert result["success"] is False
    assert result["saved"] is False
    mock_save.assert_not_called()


def test_apply_save_exception_returns_save_error(test_db_session):
    """E: save exceptions are returned as save_error instead of escaping."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.2"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["feat"],
                "summary": "manual apply",
                "superseded_by": None,
            },
            "raw_response": '{"category":"infra"}',
        },
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.save_plan_archive_result",
        side_effect=RuntimeError("save failed"),
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="apply")

    assert result["success"] is True
    assert result["saved"] is False
    assert "save failed" in result["save_error"]
