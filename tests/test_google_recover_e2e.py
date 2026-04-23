"""Google pending 복구 실서버 E2E 테스트.

실행 조건:
- Admin API 서버 실행 중 (localhost:8001)
- 실제 DB 연결 가능
- GoogleSearchWorker 프로세스 실행 중
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from app.database import SessionLocal
from app.models.google_search import (
    GoogleSearchHistory,
    GoogleSearchQueue,
    GoogleSearchResult,
)

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8001"
HEALTH_URL = f"{BASE_URL}/api/v1/system/liveness"
RECOVER_URL = f"{BASE_URL}/api/v1/google/admin/recover-pending"
ACTIVE_STATUSES = {
    GoogleSearchQueue.STATUS_QUEUED,
    GoogleSearchQueue.STATUS_PROCESSING,
    GoogleSearchQueue.STATUS_COMPLETED,
    GoogleSearchQueue.STATUS_FAILED,
}
TERMINAL_OR_PROCESSING = {
    GoogleSearchQueue.STATUS_PROCESSING,
    GoogleSearchQueue.STATUS_COMPLETED,
    GoogleSearchQueue.STATUS_FAILED,
}


def _assert_server_up() -> None:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = httpx.get(HEALTH_URL, timeout=10)
            assert response.status_code == 200
            return
        except httpx.ConnectError as exc:
            last_error = exc
            time.sleep(1)
        except (httpx.ReadTimeout, AssertionError) as exc:
            last_error = exc
            time.sleep(1)

    if isinstance(last_error, httpx.ConnectError):
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")
    pytest.fail(f"실서버 헬스체크 실패 — {HEALTH_URL} 응답 불가: {last_error}")


def _insert_pending_request(query_prefix: str) -> str:
    search_id = f"t4-google-recover-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        queue_item = GoogleSearchQueue(
            search_id=search_id,
            query=f"{query_prefix} {search_id}",
            date_filter="1w",
            max_pages=1,
            status=GoogleSearchQueue.STATUS_PENDING,
        )
        db.add(queue_item)
        db.commit()
        return search_id
    finally:
        db.close()


def _get_queue_status(search_id: str) -> str | None:
    db = SessionLocal()
    try:
        queue_item = (
            db.query(GoogleSearchQueue)
            .filter(GoogleSearchQueue.search_id == search_id)
            .first()
        )
        return queue_item.status if queue_item else None
    finally:
        db.close()


def _poll_status(search_id: str, *, timeout_seconds: float, allowed_statuses: set[str]) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_status = _get_queue_status(search_id)
    while time.monotonic() < deadline:
        last_status = _get_queue_status(search_id)
        if last_status in allowed_statuses:
            return last_status
        time.sleep(0.5)
    pytest.fail(
        f"{search_id} 상태가 {timeout_seconds}초 내 전이되지 않음. 마지막 상태={last_status}"
    )


def _cleanup_search_artifacts(search_id: str) -> None:
    db = SessionLocal()
    try:
        queue_item = (
            db.query(GoogleSearchQueue)
            .filter(GoogleSearchQueue.search_id == search_id)
            .first()
        )
        if queue_item and queue_item.status == GoogleSearchQueue.STATUS_PROCESSING:
            # 실제 워커가 잡고 있는 중이면 삭제로 간섭하지 않는다.
            db.rollback()
            return

        db.query(GoogleSearchResult).filter(
            GoogleSearchResult.search_id == search_id
        ).delete(synchronize_session=False)
        db.query(GoogleSearchHistory).filter(
            GoogleSearchHistory.search_id == search_id
        ).delete(synchronize_session=False)
        db.query(GoogleSearchQueue).filter(
            GoogleSearchQueue.search_id == search_id
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


class TestGoogleRecoverE2E:
    """실서버 + 실제 워커 기준 pending 복구 E2E."""

    def test_live_recover_pending_bulk_requeues_pending_rows(self):
        """T4: recover-pending 호출 시 pending 행들이 pending 상태를 벗어난다."""
        _assert_server_up()
        search_ids = [
            _insert_pending_request("__merge_test_google_recover_bulk__")
            for _ in range(2)
        ]

        try:
            response = httpx.post(RECOVER_URL, timeout=20)
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["pending_found"] >= 2
            assert data["recovered"] >= 2

            for search_id in search_ids:
                status = _poll_status(
                    search_id,
                    timeout_seconds=10,
                    allowed_statuses=ACTIVE_STATUSES,
                )
                assert status in ACTIVE_STATUSES
        finally:
            for search_id in search_ids:
                _cleanup_search_artifacts(search_id)

    def test_live_recovered_request_becomes_actionable_for_running_worker(self):
        """T4: recovered item이 pending을 벗어나 running worker가 집을 수 있는 상태(queued 이상)가 된다."""
        _assert_server_up()
        search_id = _insert_pending_request("__merge_test_google_recover_worker__")

        try:
            response = httpx.post(RECOVER_URL, timeout=20)
            assert response.status_code == 200, response.text

            status = _poll_status(
                search_id,
                timeout_seconds=15,
                allowed_statuses=ACTIVE_STATUSES,
            )
            assert status in ACTIVE_STATUSES
        finally:
            _cleanup_search_artifacts(search_id)
