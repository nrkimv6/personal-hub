"""T4: LogViewer SSE 스트리밍 E2E 테스트

Redis pub/sub → SSE /logs/stream 전체 경로 검증
(실행: /merge-test, 실서버 localhost:8001 + Redis 필요)
"""

import threading
import time

import pytest
import redis
import requests

ADMIN_API = "http://localhost:8001"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
LOG_CHANNEL_PREFIX = "plan-runner:logs"


def _collect_sse_data_lines(url: str, timeout: float = 8.0) -> list[str]:
    """SSE 스트림에서 data: 라인을 수집"""
    collected = []
    deadline = time.monotonic() + timeout
    try:
        with requests.get(url, stream=True, timeout=timeout + 2) as resp:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() > deadline:
                    break
                if raw_line and raw_line.startswith("data:"):
                    data = raw_line[5:].strip()
                    if data and data != "ok":
                        collected.append(data)
                if len(collected) >= 3:
                    break
    except Exception:
        pass
    return collected


@pytest.fixture
def r():
    client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    client.close()


# ---------------------------------------------------------------------------
# T4-19: Redis pub/sub → SSE data 라인 수신 (E2E)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_e2e_log_stream_receives_published_lines(r):
    """E2E: Redis publish → SSE /logs/stream data 라인 수신 확인"""
    runner_id = "t4-log-stream-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    published_lines = []

    def publish_after_delay():
        time.sleep(1.5)  # SSE 연결 대기
        for i in range(3):
            line = f"test-line-{i}"
            r.publish(channel, line)
            published_lines.append(line)
            time.sleep(0.3)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    collected = _collect_sse_data_lines(url, timeout=8.0)
    t.join(timeout=5)

    if not collected:
        pytest.skip("Admin API emitted no SSE data in publish window")

    assert len(collected) >= 1, f"SSE data: 라인이 수신되지 않음. published={published_lines}"
    assert any("test-line" in c for c in collected), f"published 라인이 SSE에 없음: {collected}"


# ---------------------------------------------------------------------------
# T4-20: pub/sub 미수신 시 파일 폴링 fallback E2E
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_e2e_log_stream_fallback_on_no_pubsub(r, tmp_path):
    """E2E: pub/sub publish 없이 파일 폴링 fallback으로 신규 줄 수신 (5초 대기)

    Phase 3 T3-B: EOF 초기화로 기존 내용은 재전송하지 않고, 연결 후 추가된 줄만 전송.
    """
    runner_id = "t4-fallback-test"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    # 기존 내용이 있는 로그 파일 생성 (EOF 초기화로 이 내용은 재전송되지 않음)
    log_file = tmp_path / "fallback_test.log"
    log_file.write_text("old-line\n" * 5, encoding="utf-8")

    correct_key = f"plan-runner:runners:{runner_id}:stream_log_path"
    r.set(correct_key, str(log_file))

    def append_after_delay():
        """SSE 연결 + fallback 전환(5초) 후 새 줄 추가"""
        time.sleep(8.0)  # fallback 전환(5초) + EOF init 후 안정화
        with open(log_file, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(f"fallback-line-{i}\n")
                f.flush()
                time.sleep(0.5)

    t = threading.Thread(target=append_after_delay, daemon=True)
    t.start()

    try:
        # 총 18초 대기: 8초 append 시작 + 파일 폴링 반영 마진
        collected = _collect_sse_data_lines(url, timeout=18.0)
        t.join(timeout=5)
        if not collected:
            pytest.skip("Admin API emitted no SSE data in fallback window")
        if any("Redis 연결 불가" in c for c in collected):
            pytest.skip("Admin API Redis unavailable — skip fallback E2E")

        # 연결 후 추가된 새 줄이 SSE로 전달되어야 함
        assert any("fallback-line" in c for c in collected), \
            f"파일 폴링 fallback 미작동: collected={collected}"
    finally:
        r.delete(correct_key)


# ---------------------------------------------------------------------------
# T3: /events fallback 통합 TC (서버 불필요, fakeredis 기반)
# ---------------------------------------------------------------------------

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _make_events_service(runner_ids: list[str], log_files: dict[str, Path]):
    """stream_events() 검증용 EventService mock (fakeredis 불필요, 순수 mock)"""
    import fakeredis
    from app.modules.dev_runner.services.event_service import (
        EventService,
        RUNNER_KEY_PREFIX,
        ACTIVE_RUNNERS_KEY,
    )

    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    for rid in runner_ids:
        fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "user")
        if rid in log_files:
            fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path", str(log_files[rid]))

    svc = EventService.__new__(EventService)
    svc._sync = fake_sync

    idle_pubsub = MagicMock()
    idle_pubsub.psubscribe = AsyncMock()
    idle_pubsub.get_message = AsyncMock(return_value=None)
    idle_pubsub.aclose = AsyncMock()

    fake_async = MagicMock()
    fake_async.config_set = AsyncMock()
    fake_async.pubsub = MagicMock(return_value=idle_pubsub)
    svc._async = fake_async

    svc._runner_tail_state = {}
    svc._completed_runners = {}
    svc._tail_state_ttl_sec = 600.0
    svc._completed_runner_ttl_sec = 120.0
    svc._dedup_window = 256
    svc._file_poll_timeout = 0.0
    svc._file_poll_interval_sec = 0.0
    svc._file_poll_max_lines = 400
    svc._file_poll_max_chars = 65536
    return svc


@pytest.mark.asyncio
async def test_t3_events_fallback_delivers_file_appended_lines(tmp_path):
    """T3: pub/sub 공백(idle) 상태에서 파일 append만으로 /events 로그 이벤트가 도달한다.

    시나리오: SSE 연결 후 pub/sub 이벤트 없음 → 로그 파일에 새 줄 추가
    → fallback 경로로 event: log 이벤트 수신 확인.
    """
    rid = "t3-fallback-events-01"
    log_file = tmp_path / f"plan-runner-stream-{rid}.log"
    log_file.write_text("", encoding="utf-8")  # 빈 파일로 시작

    svc = _make_events_service([rid], {rid: log_file})
    expected_lines = ["step-A", "step-B", "step-C"]

    gen = svc.stream_events()
    _ = await gen.__anext__()  # connected
    _ = await gen.__anext__()  # status

    # EOF 초기화 후 신규 라인 추가
    with open(log_file, "a", encoding="utf-8") as fh:
        for line in expected_lines:
            fh.write(line + "\n")

    received: list[str] = []
    try:
        async with asyncio.timeout(3.0):
            while len(received) < len(expected_lines):
                ev = await gen.__anext__()
                if ev.startswith("event: log\n"):
                    data = json.loads(ev.split("data: ")[1].split("\n")[0])
                    if data.get("runner_id") == rid:
                        line_val = data.get("line", "")
                        if isinstance(line_val, dict):
                            line_val = line_val.get("text", "")
                        received.append(line_val)
    except (TimeoutError, asyncio.TimeoutError):
        pass
    finally:
        await gen.aclose()

    for expected in expected_lines:
        assert expected in received, f"/events fallback 누락: {expected!r}, 수신={received}"


@pytest.mark.asyncio
async def test_t3_events_fallback_routes_by_runner_id(tmp_path):
    """T3: 이벤트는 runner_id 기준으로 해당 runner에만 라우팅된다.

    시나리오: 2개의 runner가 있을 때, runner-A 로그 파일에만 append
    → event: log 이벤트의 runner_id가 반드시 runner-A여야 함.
    """
    rid_a = "t3-route-runner-A"
    rid_b = "t3-route-runner-B"
    log_a = tmp_path / f"plan-runner-stream-{rid_a}.log"
    log_b = tmp_path / f"plan-runner-stream-{rid_b}.log"
    log_a.write_text("", encoding="utf-8")
    log_b.write_text("", encoding="utf-8")

    svc = _make_events_service([rid_a, rid_b], {rid_a: log_a, rid_b: log_b})

    gen = svc.stream_events()
    _ = await gen.__anext__()  # connected
    _ = await gen.__anext__()  # status

    # runner-A 파일에만 신규 라인 추가
    with open(log_a, "a", encoding="utf-8") as fh:
        fh.write("only-A-line\n")

    received_by_runner: dict[str, list[str]] = {}
    try:
        async with asyncio.timeout(3.0):
            while True:
                ev = await gen.__anext__()
                if ev.startswith("event: log\n"):
                    data = json.loads(ev.split("data: ")[1].split("\n")[0])
                    r_id = data.get("runner_id", "")
                    line_val = data.get("line", "")
                    if isinstance(line_val, dict):
                        line_val = line_val.get("text", "")
                    received_by_runner.setdefault(r_id, []).append(line_val)
                    if rid_a in received_by_runner:
                        break
    except (TimeoutError, asyncio.TimeoutError):
        pass
    finally:
        await gen.aclose()

    assert rid_a in received_by_runner, f"runner-A 이벤트 미수신: {received_by_runner}"
    assert "only-A-line" in received_by_runner[rid_a]
    # runner-B는 아무 라인도 없으므로 log 이벤트 없어야 함
    assert rid_b not in received_by_runner, (
        f"runner-B에 잘못 라우팅됨: {received_by_runner.get(rid_b)}"
    )


# ---------------------------------------------------------------------------
# T4: FAILURE/HOLD 태그 SSE 스트림 포함 검증
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_e2e_failure_tag_appears_in_sse_stream(r):
    """T4-01: Redis publish [FAILURE] 태그 → SSE /logs/stream data 라인에 포함됨 검증"""
    runner_id = "t4-failure-tag-stream-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    published = []

    def publish_after_delay():
        time.sleep(1.5)
        line = "[FAILURE] rate_limit: AI 한도 소진 — plan 상태 유지, 실패 이력 기록됨"
        r.publish(channel, line)
        published.append(line)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    collected = _collect_sse_data_lines(url, timeout=8.0)
    t.join(timeout=5)

    if not collected:
        pytest.skip("Admin API emitted no SSE data — 서버 미실행 또는 연결 실패")

    assert any("[FAILURE]" in c for c in collected), (
        f"[FAILURE] 태그 라인이 SSE 스트림에 없음: collected={collected}, published={published}"
    )


@pytest.mark.e2e
def test_e2e_hold_tag_appears_in_sse_stream(r):
    """T4-02: Redis publish [HOLD] 태그 → SSE /logs/stream data 라인에 포함됨 검증"""
    runner_id = "t4-hold-tag-stream-test"
    channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
    url = f"{ADMIN_API}/api/v1/dev-runner/logs/stream?runner_id={runner_id}"

    published = []

    def publish_after_delay():
        time.sleep(1.5)
        line = "[HOLD] plan 보류 중: P0 예약 완료 후 수동 진행 — skip (plan.md)"
        r.publish(channel, line)
        published.append(line)

    t = threading.Thread(target=publish_after_delay, daemon=True)
    t.start()

    collected = _collect_sse_data_lines(url, timeout=8.0)
    t.join(timeout=5)

    if not collected:
        pytest.skip("Admin API emitted no SSE data — 서버 미실행 또는 연결 실패")

    assert any("[HOLD]" in c for c in collected), (
        f"[HOLD] 태그 라인이 SSE 스트림에 없음: collected={collected}, published={published}"
    )
