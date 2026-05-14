"""Live E2E coverage for LLM cleanup hard delete FK behavior."""

import pytest

from tests.test_llm_live_http import (
    _cleanup_live_child_rows,
    _delete_live_request,
    _get,
    _post,
    _seed_old_completed_request_with_children,
)

pytestmark = [pytest.mark.e2e, pytest.mark.http_live]


def test_llm_cleanup_hard_delete_no_fk_violation_live_e2e():
    """R: live cleanup hard delete returns 200 and preserves child rows."""
    readiness = _get("/api/v1/system/liveness", timeout=10)
    assert readiness.status_code == 200

    request_id, writing_id, report_id = _seed_old_completed_request_with_children(
        "cleanup-hard-delete-e2e"
    )
    try:
        resp = _post("/api/v1/llm/cleanup/history?days=30&hard_delete=true", timeout=30)
        assert resp.status_code == 200, resp.text[:500]
    finally:
        _delete_live_request(request_id)
        _cleanup_live_child_rows(writing_id, report_id)
