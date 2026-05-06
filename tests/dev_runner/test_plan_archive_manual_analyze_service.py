"""Manual Plan Archive analyze service tests."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from unittest.mock import patch

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.services.plan_archive_prompt_policy import PromptPolicyContext
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


def test_preview_does_not_require_retrieval_readiness_tables(test_db_session):
    """R: manual analyze preview is independent from retrieval DB readiness."""
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
            },
            "raw_response": '{"category":"infra"}',
        },
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is True
    assert result["mode"] == "preview"


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
    assert result["save_outcome_status"] == "saved"
    assert result["save_outcome_reason"] is None
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
    assert result["save_outcome_status"] == "error"
    assert result["save_outcome_reason"] == "save failed"
    assert "save failed" in result["save_error"]


def test_apply_save_false_preserves_bool_wrapper_contract_with_outcome_metadata(test_db_session):
    """B: save_plan_archive_result bool wrapper가 False를 반환해도 apply 응답은 reason을 보존한다."""
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
        return_value=False,
    ) as mock_save:
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="apply")

    assert result["success"] is True
    assert result["saved"] is False
    assert result["save_error"] == "SAVE_PLAN_ARCHIVE_RESULT_FAILED"
    assert result["save_outcome_status"] == "failed"
    assert result["save_outcome_reason"] == "SAVE_PLAN_ARCHIVE_RESULT_FAILED"
    mock_save.assert_called_once()


def test_analyze_passes_resolved_provider_model_to_policy_builder(test_db_session):
    """R: resolved provider/model are passed into PromptPolicyContext."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")
    captured: dict[str, PromptPolicyContext] = {}

    def fake_build_prompt(ctx: PromptPolicyContext, file_content: str):
        captured["ctx"] = ctx
        captured["file_content"] = file_content
        return "PROMPT", "plan_archive.gemini.pro_preview", "test-version"

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("gemini", "gemini-3.1-pro-preview"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.build_plan_archive_prompt",
        side_effect=fake_build_prompt,
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["fix"],
                "summary": "summary",
                "superseded_by": None,
                "intent": "intent",
                "trigger": "bug_recurrence",
                "scope": ["app/example.py"],
            },
            "raw_response": "{}",
        },
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is True
    assert captured["ctx"].provider == "gemini"
    assert captured["ctx"].model == "gemini-3.1-pro-preview"
    assert captured["file_content"] == "# Manual\ncontent"


def test_analyze_response_includes_prompt_policy_metadata(test_db_session):
    """R: manual preview response exposes prompt policy metadata."""
    record = _add_record(test_db_session, raw_content="# Manual\ncontent")

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("codex", "gpt-5.5"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["fix"],
                "summary": "summary",
                "superseded_by": None,
                "intent": "intent",
                "trigger": "bug_recurrence",
                "scope": ["app/example.py"],
            },
            "raw_response": "{}",
        },
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is True
    assert result["prompt_policy_id"] == "plan_archive.codex.default"
    assert result["prompt_policy_version"]
