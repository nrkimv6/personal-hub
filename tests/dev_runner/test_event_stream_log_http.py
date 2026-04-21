"""T3/T4: EventService 로그 통합 HTTP 통합 테스트

실행 중인 Admin API 서버(localhost:8001) + Redis를 대상으로
SSE /events 스트림에서 log/log_completed/merge_log 이벤트 수신을 확인한다.
"""

import json
import threading
import time
from unittest.mock import AsyncMock, patch

import fakeredis
import fakeredis.aioredis
import pytest
import redis
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.events import router as events_router

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
BASE_URL = "/api/v1/dev-runner"

LOG_CHANNEL_PREFIX = "plan-runner:logs"
MERGE_LOG_CHANNEL = "plan-runner:merge-log"
TEST_RUNNER_ID = "t3t4-test-runner"


def _collect_sse_events(url: str, target_events: set[str], timeout: float = 5.0) -> dict[str, list[str]]:
    """SSE 스트림에서 target_events에 해당하는 이벤트를 수집하고 반환.

    반환: { event_name: [data, ...] }
    """
    collected: dict[str, list[str]] = {e: [] for e in target_events}
    deadline = time.monotonic() + timeout

    try:
        with requests.get(url, stream=True, timeout=timeout + 1) as resp:
            current_event = "message"
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if not raw_line:
                    current_event = "message"
                    continue
                if raw_line.startswith("event:"):
                    current_event = raw_line[6:].strip()
                elif raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if current_event in collected:
                        collected[current_event].append(data)
                        # 모든 타깃 수집 완료 시 조기 종료
                        if all(collected[e] for e in target_events):
                            break
    except Exception:
        pass

    return collected


def _parse_sse_events(content: str) -> list[dict[str, str]]:
    """TestClient SSE 응답 텍스트를 이벤트 목록으로 파싱."""
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in content.splitlines():
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current["data"] = line[5:].strip()
    if current:
        events.append(current)
    return events


@pytest.fixture
def r():
    """실제 Redis DB 0 클라이언트"""
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def local_client():
    app = FastAPI()
    app.include_router(events_router, prefix=BASE_URL)
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.http
def test_http_events_log_completed_commit_failed_preserves_error_detail(local_client):
    """T3: /events route는 log_completed의 commit_failed reason + error detail pair를 그대로 전달한다."""
    detail = "exit_reason=commit_failed; detail=commit_scope=docs/plan/test.md"

    async def _fake_stream_events():
        yield "event: connected\ndata: ok\n\n"
        yield (
            "event: log_completed\ndata: "
            + json.dumps(
                {
                    "runner_id": "http-t3-runner",
                    "status": "failed",
                    "reason": "commit_failed",
                    "error": detail,
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    with patch(
        "app.modules.dev_runner.routes.events.event_service.stream_events",
        new=_fake_stream_events,
    ):
        response = local_client.get(
            f"{BASE_URL}/events",
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    events = _parse_sse_events(response.text)
    completed = next(event for event in events if event.get("event") == "log_completed")
    payload = json.loads(completed["data"])
    assert payload["reason"] == "commit_failed"
    assert payload["error"] == detail


@pytest.mark.http
def test_http_events_merge_log_completed_failed_reason_preserved(local_client):
    """T5: /events route는 merge_log_completed의 merge_failed reason을 그대로 전달한다."""

    async def _fake_stream_events():
        yield "event: connected\ndata: ok\n\n"
        yield (
            "event: merge_log_completed\ndata: "
            + json.dumps(
                {
                    "runner_id": "http-merge-failed-runner",
                    "status": "failed",
                    "reason": "merge_failed",
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    with patch(
        "app.modules.dev_runner.routes.events.event_service.stream_events",
        new=_fake_stream_events,
    ):
        response = local_client.get(
            f"{BASE_URL}/events",
            headers={"Accept": "text/event-stream"},
        )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    completed = next(event for event in events if event.get("event") == "merge_log_completed")
    payload = json.loads(completed["data"])
    assert payload["status"] == "failed"
    assert payload["reason"] == "merge_failed"


@pytest.mark.http
def test_http_events_initial_status_includes_merge_recovery_fields(local_client):
    """T5: /events 초기 status가 merge 복구 필드를 포함한다."""
    from app.modules.dev_runner.services.event_service import event_service

    fake_server = fakeredis.FakeServer()
    fake_sync = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
    fake_async = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
    runner_id = "http-merge-recovery-01"
    expected_worktree = f"D:/tmp/.worktrees/{runner_id}"

    fake_sync.sadd("plan-runner:active_runners", runner_id)
    fake_sync.set(f"plan-runner:runners:{runner_id}:status", "running")
    fake_sync.set(f"plan-runner:runners:{runner_id}:trigger", "user")
    fake_sync.set(f"plan-runner:runners:{runner_id}:plan_file", "docs/plan/test.md")
    fake_sync.set(f"plan-runner:runners:{runner_id}:worktree_path", expected_worktree)
    fake_sync.set(f"plan-runner:runners:{runner_id}:merge_status", "conflict")
    fake_sync.set(f"plan-runner:runners:{runner_id}:stop_stage", "post_review")

    original_sync = event_service._sync
    original_async = event_service._async
    real_stream_events = event_service.stream_events

    async def _finite_stream_events():
        gen = real_stream_events()
        try:
            yield await gen.__anext__()
            yield await gen.__anext__()
        finally:
            await gen.aclose()

    event_service._sync = fake_sync
    event_service._async = fake_async
    try:
        with patch.object(event_service, "_enable_keyspace_notifications", new=AsyncMock(return_value=None)), \
             patch.object(event_service, "_list_visible_active_runner_ids", return_value=[]), \
             patch.object(event_service, "_cleanup_invisible_recent_runners", return_value=None), \
             patch.object(event_service._log_tailer, "init_offsets_for_active_runners", new=AsyncMock(return_value=None)), \
             patch("app.modules.dev_runner.routes.events.event_service.stream_events", new=_finite_stream_events):
            response = local_client.get(
                f"{BASE_URL}/events",
                headers={"Accept": "text/event-stream"},
            )
    finally:
        event_service._sync = original_sync
        event_service._async = original_async

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    events = _parse_sse_events(response.text)
    status_event = next(event for event in events if event.get("event") == "status")
    payload = json.loads(status_event["data"])
    matched = next(item for item in payload["runners"] if item.get("runner_id") == runner_id)
    assert matched["worktree_path"] == expected_worktree
    assert matched["merge_status"] == "conflict"
    assert matched["stop_stage"] == "post_review"


@pytest.mark.integration
class TestEventStreamLogIntegration:
    """T3/T4: /events SSE에서 log/merge_log 이벤트 수신 확인"""

    def test_sse_events_stream_connected_and_status(self):
        """T4: GET /events → connected + status 초기 이벤트 수신 (기존 동작 회귀)"""
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        collected = _collect_sse_events(url, {"connected", "status"}, timeout=5.0)
        assert collected["connected"], "connected 이벤트 미수신"
        assert collected["status"], "status 이벤트 미수신"

    def test_sse_events_stream_log_event(self, r):
        """T4: Redis에 로그 publish → SSE에서 event: log 수신"""
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        test_line = f"[TEST] hello from T4 test at {time.time()}"
        channel = f"{LOG_CHANNEL_PREFIX}:{TEST_RUNNER_ID}"

        collected: dict[str, list[str]] = {"log": []}
        errors = []

        def collect():
            try:
                with requests.get(url, stream=True, timeout=6) as resp:
                    current_event = "message"
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            current_event = "message"
                            continue
                        if raw_line.startswith("event:"):
                            current_event = raw_line[6:].strip()
                        elif raw_line.startswith("data:"):
                            data = raw_line[5:].strip()
                            if current_event == "log":
                                collected["log"].append(data)
                                return  # 첫 log 이벤트 수집 후 종료
            except Exception as e:
                errors.append(str(e))

        t = threading.Thread(target=collect, daemon=True)
        t.start()

        # SSE 연결 안정화 대기 후 publish
        time.sleep(3.0)
        r.publish(channel, test_line)

        t.join(timeout=5)

        assert not errors, f"SSE 수집 중 에러: {errors}"
        assert collected["log"], "event: log 미수신"

        payload = json.loads(collected["log"][0])
        assert payload["runner_id"] == TEST_RUNNER_ID
        assert payload["line"] == test_line

    def test_sse_events_stream_log_completed(self, r):
        """T3: Redis에 __COMPLETED__ publish → SSE에서 event: log_completed 수신"""
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        channel = f"{LOG_CHANNEL_PREFIX}:{TEST_RUNNER_ID}"

        collected: dict[str, list[str]] = {"log_completed": []}

        def collect():
            try:
                with requests.get(url, stream=True, timeout=6) as resp:
                    current_event = "message"
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            current_event = "message"
                            continue
                        if raw_line.startswith("event:"):
                            current_event = raw_line[6:].strip()
                        elif raw_line.startswith("data:"):
                            data = raw_line[5:].strip()
                            if current_event == "log_completed":
                                collected["log_completed"].append(data)
                                return
            except Exception:
                pass

        t = threading.Thread(target=collect, daemon=True)
        t.start()
        time.sleep(3.0)
        r.publish(channel, "__COMPLETED__")
        t.join(timeout=5)

        assert collected["log_completed"], "event: log_completed 미수신"
        payload = json.loads(collected["log_completed"][0])
        assert payload["runner_id"] == TEST_RUNNER_ID

    def test_sse_events_stream_merge_log(self, r):
        """T3: Redis에 merge-log publish → SSE에서 event: merge_log 수신"""
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        channel = f"{MERGE_LOG_CHANNEL}:{TEST_RUNNER_ID}"
        test_line = f"[MERGE] test merge line at {time.time()}"

        collected: dict[str, list[str]] = {"merge_log": []}

        def collect():
            try:
                with requests.get(url, stream=True, timeout=6) as resp:
                    current_event = "message"
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            current_event = "message"
                            continue
                        if raw_line.startswith("event:"):
                            current_event = raw_line[6:].strip()
                        elif raw_line.startswith("data:"):
                            data = raw_line[5:].strip()
                            if current_event == "merge_log":
                                collected["merge_log"].append(data)
                                return
            except Exception:
                pass

        t = threading.Thread(target=collect, daemon=True)
        t.start()
        time.sleep(3.0)
        r.publish(channel, test_line)
        t.join(timeout=5)

        assert collected["merge_log"], "event: merge_log 미수신"
        payload = json.loads(collected["merge_log"][0])
        assert payload["runner_id"] == TEST_RUNNER_ID
        assert payload["line"] == test_line

    def test_sse_events_stream_merge_log_completed(self, r):
        """T4/T5: merge-log sentinel publish → SSE에서 event: merge_log_completed 수신"""
        url = f"{ADMIN_API}/api/v1/dev-runner/events"
        channel = f"{MERGE_LOG_CHANNEL}:{TEST_RUNNER_ID}"

        collected: dict[str, list[str]] = {"merge_log_completed": []}

        def collect():
            try:
                with requests.get(url, stream=True, timeout=6) as resp:
                    current_event = "message"
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            current_event = "message"
                            continue
                        if raw_line.startswith("event:"):
                            current_event = raw_line[6:].strip()
                        elif raw_line.startswith("data:"):
                            data = raw_line[5:].strip()
                            if current_event == "merge_log_completed":
                                collected["merge_log_completed"].append(data)
                                return
            except Exception:
                pass

        t = threading.Thread(target=collect, daemon=True)
        t.start()
        time.sleep(3.0)
        r.publish(channel, "__MERGE_COMPLETED__")
        t.join(timeout=5)

        assert collected["merge_log_completed"], "event: merge_log_completed 미수신"
        payload = json.loads(collected["merge_log_completed"][0])
        assert payload["runner_id"] == TEST_RUNNER_ID
        assert payload["status"] == "success"
        assert payload["reason"] == "completed"
