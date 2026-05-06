"""[T5: http_live] running admin API 8001에 직접 접근한다."""

import os
from pathlib import Path
from typing import Any

import pytest

from app.core.database import SessionLocal
from app.models.plan_archive_execution import PlanArchiveExecutionJob
from app.modules.claude_worker.models.llm_request import (
    LLMProfileAssignment,
    LLMRequest,
    LLMRequestProfileClaim,
)
from tests.dev_runner.live_http_readiness import live_get_after_readiness, live_post_after_readiness


pytestmark = pytest.mark.http_live

TARGET_READBACK_FIELDS = (
    "requested_provider",
    "requested_model",
    "requested_engine",
    "requested_profile_name",
    "requested_profile_key",
    "target_label",
    "requested_target",
    "effective_target",
    "actual_target",
    "effective_provider_model",
    "actual_provider_model",
    "assigned_profile",
)
SAVE_OUTCOME_FIELDS = ("save_outcome_status", "save_outcome_reason")
TARGET_OBJECT_FIELDS = ("provider", "model", "profile_key", "engine", "profile_name")


def _assert_target_readback_fields(row: dict[str, Any]) -> None:
    for field in TARGET_READBACK_FIELDS + SAVE_OUTCOME_FIELDS:
        assert field in row

    for field in (
        "requested_target",
        "effective_target",
        "actual_target",
        "effective_provider_model",
        "actual_provider_model",
        "assigned_profile",
    ):
        target = row.get(field)
        if target is not None:
            assert isinstance(target, dict)
            for target_field in TARGET_OBJECT_FIELDS:
                assert target_field in target


def _archive_request_items(page_size: int = 5) -> list[dict[str, Any]]:
    response = live_get_after_readiness(
        f"/api/v1/plans/records/archive-llm-requests?page=1&page_size={page_size}"
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("items"), list)
    return payload["items"]


def _first_archive_request_id() -> int:
    items = _archive_request_items()
    if not items:
        pytest.skip("live archive queue has no request rows to inspect")
    request_id = items[0].get("id")
    assert isinstance(request_id, int)
    return request_id


def _first_live_analysis_record_id() -> int:
    response = live_get_after_readiness(
        "/api/v1/plans/records/archive-candidates?include_temp=true&eligible=true&limit=50",
        skip_on_readiness_failure=True,
    )
    assert response.status_code == 200
    payload = response.json()
    candidates = payload.get("candidates")
    assert isinstance(candidates, list)
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("eligible_for_analysis"):
            continue
        record = candidate.get("record")
        if isinstance(record, dict) and isinstance(record.get("id"), int):
            return record["id"]
    pytest.skip("live archive candidates have no DB-backed analysis record to queue")


def _cleanup_live_write_rows(*, request_ids: list[int], job_ids: list[int]) -> None:
    """Best-effort rollback for rows created by the gated live write test."""

    if not request_ids and not job_ids:
        return
    db = SessionLocal()
    try:
        if job_ids:
            db.query(PlanArchiveExecutionJob).filter(
                PlanArchiveExecutionJob.id.in_(job_ids)
            ).delete(synchronize_session=False)
        if request_ids:
            db.query(LLMRequestProfileClaim).filter(
                LLMRequestProfileClaim.request_id.in_(request_ids)
            ).delete(synchronize_session=False)
            db.query(LLMProfileAssignment).filter(
                LLMProfileAssignment.request_id.in_(request_ids)
            ).delete(synchronize_session=False)
            db.query(LLMRequest).filter(
                LLMRequest.id.in_(request_ids),
                LLMRequest.caller_type == "plan_archive_analyze",
                LLMRequest.requested_by == "api",
            ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def test_archive_health_live() -> None:
    response = live_get_after_readiness("/api/v1/plans/records/archive-health")
    assert response.status_code == 200

    payload = response.json()
    for key in ("archived_total", "plan_archive_schedule", "retrieval_db_readiness"):
        assert key in payload


def test_archive_candidates_live() -> None:
    response = live_get_after_readiness("/api/v1/plans/records/archive-candidates?limit=1")
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload.get("candidates"), list)


def test_archive_schedule_dashboard_live() -> None:
    response = live_get_after_readiness("/api/v1/plans/records/archive-schedule-dashboard")
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload, dict)
    assert any(key in payload for key in ("schedule", "queue", "latest_run", "summary", "health"))


def test_archive_schedule_runs_live() -> None:
    response = live_get_after_readiness(
        "/api/v1/plans/records/archive-schedule-runs?page=1&page_size=1"
    )
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload.get("items", payload.get("runs")), list)


def test_archive_queue_live_returns_target_readback_fields() -> None:
    items = _archive_request_items()
    if not items:
        pytest.skip("live archive queue has no request rows to inspect")

    _assert_target_readback_fields(items[0])


def test_archive_request_detail_live_returns_target_readback_fields() -> None:
    request_id = _first_archive_request_id()

    response = live_get_after_readiness(f"/api/v1/plans/records/archive-llm-requests/{request_id}")
    assert response.status_code == 200

    _assert_target_readback_fields(response.json())


def test_archive_attempt_history_live_returns_target_readback_fields() -> None:
    response = live_get_after_readiness(
        "/api/v1/plans/records/archive-execution-attempts?page=1&page_size=5"
    )
    assert response.status_code == 200

    payload = response.json()
    items = payload.get("items")
    assert isinstance(items, list)
    if not items:
        pytest.skip("live archive attempt history has no rows to inspect")
    _assert_target_readback_fields(items[0])


def test_archive_live_write_preserves_selected_target_when_enabled() -> None:
    if os.environ.get("MONITOR_ALLOW_PLAN_ARCHIVE_LIVE_WRITE") != "1":
        pytest.skip("set MONITOR_ALLOW_PLAN_ARCHIVE_LIVE_WRITE=1 to run the gated live write check")

    created_request_ids: list[int] = []
    created_job_ids: list[int] = []
    selected_target = {
        "provider": "codex",
        "model": "gpt-5.5",
        "label": "codex/gpt-5.5",
    }
    try:
        response = live_post_after_readiness(
            "/api/v1/plans/records/archive-executions/run",
            json={
                "record_ids": [_first_live_analysis_record_id()],
                "selected_targets": [selected_target],
            },
            skip_on_readiness_failure=True,
        )
        assert response.status_code == 200

        payload = response.json()
        if payload.get("skipped_active_request") or payload.get("skipped_active_job"):
            pytest.skip(f"live archive queue already has active work: {payload}")
        request_ids = payload.get("request_ids")
        job_ids = payload.get("job_ids")
        assert isinstance(request_ids, list)
        assert isinstance(job_ids, list)
        assert request_ids
        created_request_ids = [rid for rid in request_ids if isinstance(rid, int)]
        created_job_ids = [jid for jid in job_ids if isinstance(jid, int)]
        assert created_request_ids

        detail = live_get_after_readiness(
            f"/api/v1/plans/records/archive-llm-requests/{created_request_ids[0]}",
            skip_on_readiness_failure=True,
        )
        assert detail.status_code == 200
        detail_payload = detail.json()
        _assert_target_readback_fields(detail_payload)
        assert detail_payload["requested_target"]["provider"] == selected_target["provider"]
        assert detail_payload["requested_target"]["model"] == selected_target["model"]
    finally:
        _cleanup_live_write_rows(
            request_ids=created_request_ids,
            job_ids=created_job_ids,
        )


def test_source_contract_uses_live_http_helper() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert "live_get_after_readiness" in source
    assert "live_post_after_readiness" in source


def test_source_contract_no_testclient() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "Test" + "Client"
    assert forbidden not in source
