"""[T5: http_live] running admin API 8001에 직접 접근한다."""

from pathlib import Path

import pytest

from tests.dev_runner.live_http_readiness import live_get_after_readiness


pytestmark = pytest.mark.http_live


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


def test_source_contract_uses_live_http_helper() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert "live_get_after_readiness" in source


def test_source_contract_no_testclient() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "Test" + "Client"
    assert forbidden not in source
