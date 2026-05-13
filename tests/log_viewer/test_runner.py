"""
tests/log_viewer/test_runner.py — runner.py 단위 테스트

Redis 연동은 fakeredis 또는 unittest.mock으로 격리한다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.log_viewer.runner import (
    RunnerInfo,
    get_active_runners,
    get_runner_display_name,
    get_runner_file_id,
)


# ---------------------------------------------------------------------------
# get_runner_file_id
# ---------------------------------------------------------------------------

class TestGetRunnerFileId:
    def test_new_format_returns_hex_id(self):
        fname = "plan-runner-ab12cd34-20260305-143022.log"
        assert get_runner_file_id(fname) == "ab12cd34"

    def test_old_format_returns_hhmmss(self):
        fname = "plan-runner-20260305-143022.log"
        assert get_runner_file_id(fname) == "143022"

    def test_no_match_returns_empty(self):
        assert get_runner_file_id("some-other-file.log") == ""

    def test_empty_string_returns_empty(self):
        assert get_runner_file_id("") == ""

    def test_stream_file_returns_empty(self):
        # stream 파일은 "plan-runner-stream-..." 형식이라 패턴 불일치 → 빈 문자열
        # get_runner_file_id는 main log 파일(plan-runner-{hex}-...)에만 사용한다
        fname = "plan-runner-stream-ab12cd34-20260305-143022.log"
        result = get_runner_file_id(fname)
        assert result == ""

    # --- Phase 3: TC runner 패턴 ---

    def test_tc_runner_format_returns_name(self):
        """R(Right): TC runner 기본 형식 → t-{name} 반환"""
        fname = "plan-runner-t-my-plan-20260305-143022.log"
        assert get_runner_file_id(fname) == "t-my-plan"

    def test_tc_runner_with_numbers_non_greedy(self):
        """B(Boundary): 숫자 포함 이름 — non-greedy로 YYYYMMDD 앞에서 끊어짐"""
        fname = "plan-runner-t-test-99-20260305-143022.log"
        assert get_runner_file_id(fname) == "t-test-99"

    def test_tc_runner_single_name(self):
        """B(Boundary): 최소 이름 (한 글자)"""
        fname = "plan-runner-t-x-20260305-143022.log"
        assert get_runner_file_id(fname) == "t-x"

    def test_tc_runner_priority_over_hex(self):
        """R(Right): TC runner 패턴이 8자 hex 패턴보다 먼저 매칭됨"""
        # 이름이 마침 8자 hex처럼 생겼어도 t- 접두사 덕분에 TC runner로 인식
        fname = "plan-runner-t-ab12cd34-20260305-143022.log"
        result = get_runner_file_id(fname)
        assert result == "t-ab12cd34"


# ---------------------------------------------------------------------------
# get_runner_display_name
# ---------------------------------------------------------------------------

class TestGetRunnerDisplayName:
    def test_standard_plan_file(self):
        plan = "D:/work/2026-02-25_smart-push-auto-rebase.md"
        assert get_runner_display_name(plan) == "smart-push"

    def test_short_name_single_word(self):
        plan = "/home/user/2026-03-01_deploy.md"
        assert get_runner_display_name(plan) == "deploy"

    def test_no_date_prefix(self):
        # 날짜 접두사 없는 경우 — 첫 두 단어
        plan = "my-feature-impl.md"
        assert get_runner_display_name(plan) == "my-feature"

    def test_empty_string_returns_unknown(self):
        assert get_runner_display_name("") == "(unknown)"

    def test_fix_prefix_stripped(self):
        plan = "2026-03-10_fix-login-error.md"
        assert get_runner_display_name(plan) == "login-error"

    def test_only_date_prefix(self):
        plan = "2026-03-10_feature.md"
        assert get_runner_display_name(plan) == "feature"

    # --- Phase 3: fallback 파라미터 ---

    def test_fallback_used_when_plan_file_empty(self):
        """R(Right): plan_file이 빈 문자열이면 fallback 반환"""
        assert get_runner_display_name("", fallback="abc123") == "abc123"

    def test_fallback_default_is_unknown(self):
        # B(Boundary): fallback 미지정 시 기본값 "(unknown)"
        assert get_runner_display_name("") == "(unknown)"

    def test_fallback_ignored_when_plan_file_given(self):
        """R(Right): plan_file이 있으면 fallback 무시하고 이름 추출"""
        assert get_runner_display_name("2026-03-05_smart-push.md", fallback="xxx") == "smart-push"


# ---------------------------------------------------------------------------
# get_active_runners — Redis mock
# ---------------------------------------------------------------------------

def _make_redis_mock(runners: list[dict]) -> MagicMock:
    """fakeredis 대체: unittest.mock으로 Redis 인터페이스를 흉내 낸다."""
    r = MagicMock()

    # smembers → set of bytes
    r.smembers.return_value = {
        rid["runner_id"].encode()
        for rid in runners
        if rid.get("active", True)
    }
    r.zrevrange.return_value = [
        rid["runner_id"].encode()
        for rid in runners
        if rid.get("recent", False)
    ]
    r.zrange.return_value = r.zrevrange.return_value

    def _get(key: str):
        key_str = key if isinstance(key, str) else key.decode()
        for runner in runners:
            rid = runner["runner_id"]
            prefix = f"plan-runner:runners:{rid}"
            mapping = {
                f"{prefix}:log_file_path": runner.get("log_path"),
                f"{prefix}:stream_log_path": runner.get("stream_path"),
                f"{prefix}:plan_file": runner.get("plan_file"),
                f"{prefix}:pid": runner.get("pid"),
                f"{prefix}:merge_status": runner.get("merge_status"),
            }
            if key_str in mapping:
                val = mapping[key_str]
                return val.encode() if val else None
        return None

    r.get.side_effect = _get
    r.ping.return_value = True
    return r


class TestGetActiveRunners:
    def test_returns_runners_from_redis(self):
        mock_data = [
            {
                "runner_id": "ab12cd34",
                "log_path": "D:/logs/plan-runner-ab12cd34-20260305-100000.log",
                "stream_path": "D:/logs/plan-runner-stream-ab12cd34-20260305-100000.log",
                "plan_file": "D:/work/2026-03-05_smart-push.md",
                "pid": "1234",
            }
        ]
        r = _make_redis_mock(mock_data)
        result = get_active_runners(r)

        assert len(result) == 1
        info = result[0]
        assert info.runner_id == "ab12cd34"
        assert info.pid == "1234"
        assert info.display_name == "smart-push"
        assert info.short_id == "ab12cd34"

    def test_empty_redis_returns_empty_list(self):
        r = _make_redis_mock([])
        result = get_active_runners(r)
        assert result == []

    def test_redis_connection_failure_returns_empty(self):
        r = MagicMock()
        r.smembers.side_effect = Exception("Connection refused")
        result = get_active_runners(r)
        assert result == []

    def test_no_redis_client_connection_failure_returns_empty(self):
        """redis_client=None 이고 Redis 연결 불가 → 빈 리스트"""
        # 실제 Redis가 없을 테스트 환경에서도 예외 없이 빈 리스트 반환
        import sys
        from unittest.mock import patch

        fake_redis_mod = MagicMock()
        instance = MagicMock()
        instance.ping.side_effect = Exception("No Redis")
        fake_redis_mod.Redis.return_value = instance

        with patch.dict(sys.modules, {"redis": fake_redis_mod}):
            result = get_active_runners(None)
        assert result == []

    def test_multiple_runners(self):
        mock_data = [
            {
                "runner_id": "aaaa1111",
                "log_path": "D:/logs/plan-runner-aaaa1111-20260305-090000.log",
                "stream_path": None,
                "plan_file": "D:/work/2026-03-05_deploy-prod.md",
                "pid": "100",
            },
            {
                "runner_id": "bbbb2222",
                "log_path": "D:/logs/plan-runner-bbbb2222-20260305-100000.log",
                "stream_path": "D:/logs/plan-runner-stream-bbbb2222-20260305-100000.log",
                "plan_file": "D:/work/2026-03-01_fix-login.md",
                "pid": "200",
            },
        ]
        r = _make_redis_mock(mock_data)
        result = get_active_runners(r)

        assert len(result) == 2
        rids = {info.runner_id for info in result}
        assert rids == {"aaaa1111", "bbbb2222"}

    def test_runner_with_null_fields(self):
        """log_path 등이 None인 runner도 정상 처리"""
        mock_data = [
            {
                "runner_id": "cccc3333",
                "log_path": None,
                "stream_path": None,
                "plan_file": None,
                "pid": None,
            }
        ]
        r = _make_redis_mock(mock_data)
        result = get_active_runners(r)

        assert len(result) == 1
        info = result[0]
        assert info.runner_id == "cccc3333"
        assert info.log_path is None
        assert info.display_name == "cccc3333"  # plan_file=None → fallback to runner_id
        assert info.short_id == ""

    def test_runner_sources_include_recent_approval_required_R(self):
        """R: active set에 없어도 recent approval_required runner는 PR/PS source 후보가 된다."""
        mock_data = [
            {
                "runner_id": "approval-runner",
                "active": False,
                "recent": True,
                "merge_status": "approval_required",
                "log_path": None,
                "stream_path": "D:/logs/plan-runner-stream-approval-runner-20260513_120000.log",
                "plan_file": "D:/work/2026-05-13_fix-service-lock.md",
                "pid": None,
            }
        ]
        r = _make_redis_mock(mock_data)
        result = get_active_runners(r)

        assert len(result) == 1
        assert result[0].runner_id == "approval-runner"
        assert result[0].short_id == "approval-runner"


# ---------------------------------------------------------------------------
# RunnerInfo — display_name fallback to runner_id (Phase 3)
# ---------------------------------------------------------------------------

class TestRunnerInfoFallback:
    def test_runner_info_null_plan_shows_runner_id(self):
        # R(Right): plan_file=None, runner_id="t-my-tc" → display_name == "t-my-tc"
        info = RunnerInfo(
            runner_id="t-my-tc",
            log_path=None,
            stream_path=None,
            plan_file=None,
            pid=None,
        )
        assert info.display_name == "t-my-tc"

    def test_runner_info_with_plan_file_ignores_runner_id(self):
        """R(Right): plan_file 있으면 runner_id 무시하고 이름 추출"""
        info = RunnerInfo(
            runner_id="ignored-id",
            log_path=None,
            stream_path=None,
            plan_file="2026-03-05_deploy.md",
            pid=None,
        )
        assert info.display_name == "deploy"
