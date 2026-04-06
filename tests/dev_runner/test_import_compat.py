"""
TC: Phase T3 — import 경로 회귀 검증

이 리팩토링에서 생성한 신규 모듈들의 import 경로가
기존 소비자(~70개 테스트 파일)와 호환되는지 검증한다.

mock 없이 실제 import 사용 (sys.path 동적 로드 포함).
"""
import sys
import importlib
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"


def test_executor_service_reexports():
    """executor_service에서 re-export되는 모든 상수와 MergeService가 import 가능해야 함"""
    from app.modules.dev_runner.services.executor_service import (
        executor_service,
        ExecutorService,
        MergeService,
        ACTIVE_RUNNERS_KEY,
        RECENT_RUNNERS_KEY,
        RUNNER_KEY_PREFIX,
        RECENT_RUNNERS_TTL,
        RUNNER_KEY_SUFFIXES,
        COMMANDS_KEY,
        RESULTS_KEY,
        COMMAND_TIMEOUT,
    )
    assert ExecutorService is not None
    assert MergeService is not None
    assert isinstance(ACTIVE_RUNNERS_KEY, str)
    assert isinstance(COMMANDS_KEY, str)


def test_merge_service_direct_import():
    """MergeService를 merge_service에서 직접 import 가능해야 함"""
    from app.modules.dev_runner.services.merge_service import MergeService
    assert MergeService is not None
    # __all__ 선언 확인
    import app.modules.dev_runner.services.merge_service as mod
    assert "MergeService" in mod.__all__


def test_sse_helpers_reexports():
    """sse_helpers에서 SSE framing 유틸 import 가능해야 함"""
    from app.modules.dev_runner.services.sse_helpers import (
        safe_close_pubsub,
        _PollFrameBuffer,
        _format_sse_data,
        _truncate_sse_payload,
        _is_frame_start,
        _is_multiline_frame_enabled,
        _normalize_newlines,
        MAX_SSE_FRAME_CHARS,
        MULTILINE_FRAME_ENV,
    )
    assert callable(safe_close_pubsub)
    assert callable(_format_sse_data)
    assert isinstance(MAX_SSE_FRAME_CHARS, int)


def test_log_file_resolver_import():
    """LogFileResolver를 log_file_resolver에서 직접 import 가능해야 함"""
    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
    assert LogFileResolver is not None
    assert "LogFileResolver" in __import__(
        "app.modules.dev_runner.services.log_file_resolver",
        fromlist=["__all__"]
    ).__all__


def test_dr_runner_predicates_import():
    """scripts/_dr_runner_predicates.py에서 5개 함수 import 성공 (sys.path 동적 로드)"""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))

    from _dr_runner_predicates import (
        _is_user_visible_trigger,
        _is_pre_review_stopped_runner,
        _is_pid_alive,
        _parse_start_elapsed_seconds,
        _is_recent_runner_without_hb,
    )
    assert callable(_is_user_visible_trigger)
    assert callable(_is_pid_alive)
    assert callable(_parse_start_elapsed_seconds)


def test_dr_process_utils_still_exports_predicates():
    """_dr_process_utils에서도 predicates가 re-export되어야 함 (하위 호환)"""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))

    from _dr_process_utils import (
        _is_user_visible_trigger,
        _is_pid_alive,
        _parse_start_elapsed_seconds,
        _is_recent_runner_without_hb,
        _is_pre_review_stopped_runner,
    )
    assert callable(_is_user_visible_trigger)
    assert callable(_is_pid_alive)


def test_log_service_has_resolver():
    """LogService 인스턴스가 self.resolver(LogFileResolver) 속성을 가져야 함"""
    from unittest.mock import patch, MagicMock
    import redis.asyncio as aioredis

    with patch("app.modules.dev_runner.services.log_service.RedisClient") as mock_rc:
        mock_rc.get_sync_client.return_value = MagicMock()
        with patch("app.modules.dev_runner.services.log_service.aioredis.ConnectionPool"):
            with patch("app.modules.dev_runner.services.log_service.aioredis.Redis"):
                from app.modules.dev_runner.services.log_service import LogService
                svc = LogService()

    from app.modules.dev_runner.services.log_file_resolver import LogFileResolver
    assert isinstance(svc.resolver, LogFileResolver)


def test_executor_service_has_merge():
    """ExecutorService 인스턴스가 self.merge(MergeService) 속성을 가져야 함"""
    from app.modules.dev_runner.services.executor_service import ExecutorService
    from app.modules.dev_runner.services.merge_service import MergeService

    svc = ExecutorService()
    assert isinstance(svc.merge, MergeService)
