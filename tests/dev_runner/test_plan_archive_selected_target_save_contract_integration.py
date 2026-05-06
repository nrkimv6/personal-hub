"""Plan Archive selected target -> save outcome integration contract tests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.plan_analyze_handler import save_plan_archive_result_outcome
from app.modules.dev_runner.services.plan_archive_execution_service import PlanArchiveExecutionService


class _FakeLLMService:
    def resolve_provider_model(self, caller_type: str, provider: str | None = None, model: str | None = None):
        return provider or "codex", model or "gpt-5.5"


def _db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    return engine, session


def _record(db, *, filename_hash: str = "selected-target-record", category: str | None = None) -> PlanRecord:
    record = PlanRecord(
        filename_hash=filename_hash,
        file_path=f"/archive/{filename_hash}.md",
        raw_content="# selected target\n\nbody",
        archived_at=datetime(2026, 5, 6),
        status="archived",
        category=category,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _analysis_result(category: str, summary: str = "summary") -> dict:
    return {
        "success": True,
        "result": {
            "category": category,
            "tags": ["fix"],
            "summary": summary,
            "intent": "fix Plan Archive selected target",
            "trigger": "bug_recurrence",
            "scope": ["plan_archive"],
        },
        "raw_response": "{}",
    }


def test_enqueue_record_preserves_each_selected_target_model():
    engine, db = _db()
    try:
        record = _record(db)
        targets = [
            {
                "provider": "claude",
                "model": "claude-sonnet-4-5",
                "engine": "claude",
                "profile_name": "work",
                "profile_key": "claude:work",
                "dedupe_key": "claude:work:claude-sonnet-4-5",
                "label": "claude/work/claude-sonnet-4-5",
            },
            {
                "provider": "codex",
                "model": "gpt-5.5",
                "dedupe_key": "profileless:codex:gpt-5.5",
                "label": "codex/gpt-5.5",
            },
        ]

        result = PlanArchiveExecutionService(db).enqueue_record(
            record,
            trigger_source="test:selected-target-contract",
            selected_targets=targets,
            llm_service=_FakeLLMService(),
        )

        assert result["status_key"] == "queued"
        requests = db.query(LLMRequest).order_by(LLMRequest.id.asc()).all()
        assert [(r.provider, r.model, r.dedupe_key) for r in requests] == [
            ("claude", "claude-sonnet-4-5", "profile:claude:work:claude-sonnet-4-5"),
            ("codex", "gpt-5.5", "profileless:codex:gpt-5.5"),
        ]
    finally:
        db.close()
        engine.dispose()


def test_late_older_request_is_stale_skipped_not_failed():
    engine, db = _db()
    try:
        record = _record(db, filename_hash="stale-contract")
        PlanArchiveExecutionService(db).enqueue_record(
            record,
            trigger_source="test:selected-target-contract",
            selected_targets=[
                {"provider": "codex", "model": "gpt-5.4", "dedupe_key": "profileless:codex:gpt-5.4"},
                {"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless:codex:gpt-5.5"},
            ],
            llm_service=_FakeLLMService(),
        )
        older, newer = db.query(LLMRequest).order_by(LLMRequest.id.asc()).all()
        newer.status = "completed"
        newer.result = "{}"
        db.commit()

        newer_outcome = save_plan_archive_result_outcome(db, newer, _analysis_result("common", "newer"))
        older_outcome = save_plan_archive_result_outcome(db, older, _analysis_result("infra", "older"))

        db.refresh(record)
        assert newer_outcome.saved is True
        assert older_outcome.saved is False
        assert older_outcome.status == "stale_skipped"
        assert older_outcome.reason == "newer_completed_result_exists"
        assert record.category == "common"
        assert older.status != "failed"
    finally:
        db.close()
        engine.dispose()


def test_filename_like_category_is_rejected_and_existing_category_survives():
    engine, db = _db()
    try:
        record = _record(db, filename_hash="category-contract", category="common")
        PlanArchiveExecutionService(db).enqueue_record(
            record,
            trigger_source="test:selected-target-contract",
            selected_targets=[{"provider": "codex", "model": "gpt-5.5", "dedupe_key": "profileless:codex:gpt-5.5"}],
            llm_service=_FakeLLMService(),
        )
        request = db.query(LLMRequest).one()

        outcome = save_plan_archive_result_outcome(
            db,
            request,
            _analysis_result("2026-04-12_fix-test-fix-engine-propagation-merge-precheck-unmocked.md"),
        )

        db.refresh(record)
        assert outcome.saved is True
        assert outcome.status == "saved"
        assert outcome.reason == "invalid_category_skipped"
        assert record.category == "common"
    finally:
        db.close()
        engine.dispose()
