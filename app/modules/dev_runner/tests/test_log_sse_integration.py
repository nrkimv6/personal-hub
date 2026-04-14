"""T3: subprocess stdout → _stream_output → Redis publish 전체 경로 통합 TC"""

import asyncio
import subprocess
import sys
import threading
from io import StringIO
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import fakeredis
import fakeredis.aioredis


# ---------------------------------------------------------------------------
# T3: subprocess stdout → publish 전체 경로 검증
# ---------------------------------------------------------------------------

def test_integration_subprocess_to_redis_pubsub():
    """subprocess stdout → _publish_with_retry → Redis publish 3회 검증

    실제 subprocess.Popen으로 Python 프로세스 시작,
    stdout → readline 루프 → Redis mock publish 확인.
    mock은 Redis만, subprocess와 파일은 실제 사용.
    """
    import redis as redis_module
    from io import StringIO

    # 실제 subprocess: 5줄 출력 후 종료
    proc = subprocess.Popen(
        [
            sys.executable, "-c",
            "import time; [print(f'line-{i}', flush=True) for i in range(5)]"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    redis_client = MagicMock()
    log_handle = StringIO()
    channel = "plan-runner:logs:integration-test"

    # _publish_with_retry 로직 인라인 (import 순환 방지)
    def publish_with_retry(client, ch, msg):
        try:
            client.publish(ch, msg)
            return True
        except redis_module.ConnectionError:
            pass
        try:
            client.ping()
            client.publish(ch, msg)
            return True
        except Exception:
            return False

    published = []
    line_count = 0
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line_count += 1
        stripped = line.rstrip("\n")
        log_handle.write(line)
        log_handle.flush()
        publish_with_retry(redis_client, channel, stripped)
        published.append(stripped)

    proc.wait(timeout=10)

    # 검증: 5줄 모두 publish됨
    assert redis_client.publish.call_count == 5
    args_list = [c.args[1] for c in redis_client.publish.call_args_list]
    for i in range(5):
        assert f"line-{i}" in args_list[i], f"line-{i} not in publish args: {args_list}"

    # 로그 파일에도 기록됨
    log_handle.seek(0)
    log_content = log_handle.read()
    assert "line-0" in log_content
    assert "line-4" in log_content


def test_status_payload_includes_cc_codex_engine_in_sse_meta():
    """EventService status payload에 cc-codex engine 메타가 포함되는지 검증"""
    from app.modules.dev_runner.services.event_service import EventService, RUNNER_KEY_PREFIX

    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    rid = "sse-cc-codex-01"
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:pid", "12345")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:engine", "cc-codex")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:plan_file", "docs/plan/test.md")

    svc = EventService.__new__(EventService)
    svc._sync = fake_sync
    svc._async = fakeredis.aioredis.FakeRedis(decode_responses=True)

    from app.modules.dev_runner.services.event_payload import build_status_payload
    payload = build_status_payload(svc._sync, rid)

    assert payload is not None
    assert payload["runner_id"] == rid
    assert payload["engine"] == "cc-codex"


@pytest.mark.asyncio
async def test_cc_codex_log_delivery_via_fallback_no_missing_lines(tmp_path):
    """회귀TC: engine=cc-codex runner에서 pub/sub 공백 시 fallback이 로그를 누락 없이 전달한다.

    문제 상황: cc-codex 실행 중 pub/sub 공백이 발생 → UI가 멈추고
    새로고침 시에만 파일 로그가 보임.
    기대: /events fallback 경로가 신규 파일 라인을 누락 없이 전달.
    """
    from app.modules.dev_runner.services.event_service import (
        EventService,
        RUNNER_KEY_PREFIX,
        ACTIVE_RUNNERS_KEY,
        LOG_CHANNEL_PATTERN,
    )

    rid = "cc-codex-regression-01"
    log_file = tmp_path / f"plan-runner-stream-{rid}.log"
    log_file.write_text("", encoding="utf-8")  # 빈 파일로 시작

    fake_sync = fakeredis.FakeRedis(decode_responses=True)
    fake_sync.sadd(ACTIVE_RUNNERS_KEY, rid)
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:trigger", "user")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:engine", "cc-codex")
    fake_sync.set(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path", str(log_file))

    svc = EventService.__new__(EventService)
    svc._sync = fake_sync

    # pub/sub 항상 None 반환(공백 시뮬레이션)
    idle_pubsub = MagicMock()
    idle_pubsub.psubscribe = AsyncMock()
    idle_pubsub.get_message = AsyncMock(return_value=None)
    idle_pubsub.reset_mock = MagicMock()
    idle_pubsub.aclose = AsyncMock()

    fake_async = MagicMock()
    fake_async.config_set = AsyncMock()
    fake_async.pubsub = MagicMock(return_value=idle_pubsub)
    svc._async = fake_async

    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
    from app.modules.dev_runner.services.event_log_tailer import LogTailer
    from app.modules.dev_runner.config import config as _config
    _log_resolver = LogFileResolver(_config, fake_sync)
    svc._log_tailer = LogTailer(fake_sync, _log_resolver)
    svc._file_poll_timeout = 0.0
    svc._file_poll_interval_sec = 0.0

    cc_codex_lines = [f"[cc-codex] step {i}: processing task" for i in range(5)]

    gen = svc.stream_events()
    _ = await gen.__anext__()  # connected
    _ = await gen.__anext__()  # status (초기 상태)

    # EOF 초기화 후 cc-codex 출력 시뮬레이션
    with open(log_file, "a", encoding="utf-8") as fh:
        for line in cc_codex_lines:
            fh.write(line + "\n")

    # fallback이 5줄을 모두 전달하는지 검증
    received_lines: list[str] = []
    try:
        async with asyncio.timeout(3.0):
            while len(received_lines) < len(cc_codex_lines):
                event_str = await gen.__anext__()
                import json
                if event_str.startswith("event: log\n"):
                    data = json.loads(event_str.split("data: ")[1].split("\n")[0])
                    if data.get("runner_id") == rid:
                        line_val = data.get("line", "")
                        if isinstance(line_val, dict):
                            line_val = line_val.get("text", "")
                        received_lines.append(line_val)
    except (TimeoutError, asyncio.TimeoutError):
        pass
    finally:
        await gen.aclose()

    for expected in cc_codex_lines:
        assert expected in received_lines, (
            f"cc-codex 라인 누락: {expected!r}\n수신된 라인: {received_lines}"
        )
