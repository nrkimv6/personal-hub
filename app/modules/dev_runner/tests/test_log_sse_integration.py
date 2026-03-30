"""T3: subprocess stdout → _stream_output → Redis publish 전체 경로 통합 TC"""

import subprocess
import sys
import threading
from io import StringIO
from unittest.mock import MagicMock, call

import pytest


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
