"""fakeredis 기반 dev_runner TC 공유 헬퍼 — pytest conftest는 직접 import 불가하여 별도 모듈로 추출"""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import tempfile
import time
import sys
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_plan_paths import resolve_plan_target


@contextmanager
def mock_merge_queue_turn(repo_id: str):
    """fakeredis 기반 E2E TC에서 merge_queue 함수 mock 헬퍼.

    ⚠️ fakeredis는 Lua eval 미지원 — merge_queue.py의 acquire_merge_turn()이
    _ENQUEUE_LUA 스크립트를 eval()로 실행하므로 `unknown command 'eval'` 오류 발생.
    merge_queue 함수를 직접 호출하는 모든 TC는 반드시 이 context manager를 사용할 것.

    Usage:
        with mock_merge_queue_turn("my-repo"):
            # TC 코드 — acquire/release는 mock으로 대체됨
    """
    with patch("merge_queue.acquire_merge_turn", return_value=True), \
         patch("merge_queue.release_merge_turn", return_value=True), \
         patch("merge_queue._get_repo_id", return_value=repo_id):
        yield


def emit_codex_runtime_failure(
    redis_client,
    runner_id: str,
    *,
    plan_file: str = "docs/plan/test.md",
    trigger: str = "tc:codex_runtime_failure_http",
    exit_reason: str = "auto_plan_failed",
    stderr_lines: list[str] | None = None,
) -> Path:
    """accepted runner를 runtime 실패 상태로 전이시키는 테스트 헬퍼.

    runners API 조회용 Redis 상태와 logs/recent 조회용 stream_log_path를 함께 구성한다.
    반환값: 생성된 임시 로그 파일 경로 (테스트에서 unlink 필요).
    """
    if stderr_lines is None:
        stderr_lines = [
            "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`",
            "in `model_reasoning_effort`",
        ]

    prefix = f"plan-runner:runners:{runner_id}"
    redis_client.srem("plan-runner:active_runners", runner_id)
    redis_client.zadd("plan-runner:recent_runners", {runner_id: time.time()})
    redis_client.set(f"{prefix}:status", "failed")
    redis_client.set(f"{prefix}:engine", "codex")
    redis_client.set(f"{prefix}:trigger", trigger)
    redis_client.set(f"{prefix}:plan_file", plan_file)
    redis_client.set(f"{prefix}:start_time", datetime.now().isoformat())
    redis_client.set(f"{prefix}:exit_reason", exit_reason)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as fp:
        for line in stderr_lines:
            fp.write(f"[09:50:53] [ERROR] {line}\n")
        log_path = Path(fp.name)
    redis_client.set(f"{prefix}:stream_log_path", str(log_path))
    return log_path


def resolve_archive_or_history_path(plan_file: str) -> Path:
    """plan 파일의 규칙 기반 archive/history target 경로 반환."""
    return resolve_plan_target(plan_file, purpose="archive").target
