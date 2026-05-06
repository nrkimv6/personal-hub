"""Provider prompt policy integration tests for Plan Archive manual analyze."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from unittest.mock import patch

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.services.plan_archive_prompt_policy import (
    PromptPolicyContext,
    build_plan_archive_prompt,
)
from app.modules.dev_runner.services.plan_archive_manual_analyze_service import (
    PlanArchiveManualAnalyzeService,
)


ARCHIVE_FIXTURE = """# Fix global 401 reload

## TODO
- [x] app/routes/session.py 401 reload guard
- [x] frontend/src/routes/Login.svelte session refresh UX
- [x] regression test
"""


def _add_record(db, **kwargs) -> PlanRecord:
    record = PlanRecord(
        filename_hash=kwargs.pop("filename_hash", f"policy_integration_{uuid4().hex}"),
        file_path=kwargs.pop("file_path", "/archive/2026-02-24-fix-global-401-reload.md"),
        archived_at=kwargs.pop("archived_at", datetime.now()),
        status=kwargs.pop("status", "archived"),
        raw_content=kwargs.pop("raw_content", ARCHIVE_FIXTURE),
        **kwargs,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_three_providers_share_common_trigger_and_scope_rules():
    for provider, model in [
        ("claude", "claude-opus-4-6"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("codex", "gpt-5.5"),
    ]:
        prompt, policy_id, _version = build_plan_archive_prompt(
            PromptPolicyContext(
                caller_type="plan_archive_analyze",
                provider=provider,
                model=model,
                filename="2026-02-24-fix-global-401-reload.md",
                existing_categories=["infra", "common"],
            ),
            ARCHIVE_FIXTURE,
        )

        assert provider in policy_id
        assert "trigger 판정 규칙" in prompt
        assert "scope 우선순위는 변경 파일 경로 > 모듈명 > 기능명" in prompt


def test_manual_preview_returns_provider_specific_policy_metadata(test_db_session):
    record = _add_record(test_db_session)

    with patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.resolve_provider_model",
        return_value=("gemini", "gemini-3.1-pro-preview"),
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.LLMService.execute_llm",
        return_value={
            "success": True,
            "parsed": {
                "category": "infra",
                "tags": ["fix"],
                "summary": "401 reload guard",
                "superseded_by": None,
                "intent": "prevent auth regression",
                "trigger": "bug_recurrence",
                "scope": ["app/routes/session.py", "frontend/src/routes/Login.svelte"],
            },
            "raw_response": "{}",
        },
    ):
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="preview")

    assert result["success"] is True
    assert result["prompt_policy_id"] == "plan_archive.gemini.pro_preview"
    assert result["prompt_policy_version"]


def test_apply_mode_uses_save_plan_archive_result_only(test_db_session):
    from app.modules.claude_worker.models.llm_request import LLMRequest

    record = _add_record(test_db_session)

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
                "summary": "401 reload guard",
                "superseded_by": None,
                "intent": "prevent auth regression",
                "trigger": "bug_recurrence",
                "scope": ["app/routes/session.py"],
            },
            "raw_response": "{}",
        },
    ), patch(
        "app.modules.dev_runner.services.plan_archive_manual_analyze_service.save_plan_archive_result",
        return_value=True,
    ) as mock_save:
        result = PlanArchiveManualAnalyzeService(test_db_session).analyze(record.id, mode="apply")

    assert result["success"] is True
    mock_save.assert_called_once()
    assert test_db_session.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").count() == 0
