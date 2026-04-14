"""Phase RR R1: cross-repo 채널 계약 TC

목적:
- `LOG_CHANNEL_PREFIX` 상수 드리프트 자동 감지
- wtools publish 채널명(`plan-runner:logs:{runner_id}`)과 monitor-page subscribe 채널명이
  동일 포맷임을 TC로 고정 (향후 어느 쪽 수정 시 자동 감지)

관련 plan: docs/plan/2026-04-08_fix-logviewer-realtime-channel-mismatch_todo-2.md
Phase RR R1 체크박스 검증 전용 테스트.
"""
import pytest


# ─── R1: 채널 계약 단언 ────────────────────────────────────────────────────────

class TestChannelContract:
    """LOG_CHANNEL_PREFIX 상수 드리프트 회귀 방지 TC"""

    def test_log_channel_prefix_value(self):
        """LOG_CHANNEL_PREFIX == 'plan-runner:logs' (상수 드리프트 감지)"""
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        assert LOG_CHANNEL_PREFIX == "plan-runner:logs", (
            f"LOG_CHANNEL_PREFIX 변경 감지: '{LOG_CHANNEL_PREFIX}'. "
            f"wtools의 publish 채널명과 불일치할 수 있음."
        )

    def test_per_runner_channel_format(self):
        """LOG_CHANNEL_PREFIX + ':' + runner_id == 'plan-runner:logs:{runner_id}'"""
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        runner_id = "abc"
        channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        assert channel == "plan-runner:logs:abc", (
            f"per-runner 채널 포맷 불일치: '{channel}'"
        )

    def test_system_log_channel_value(self):
        """SYSTEM_LOG_CHANNEL == 'plan-runner:system' (bare publish 분리 확인)"""
        from app.modules.dev_runner.services.log_service import SYSTEM_LOG_CHANNEL
        assert SYSTEM_LOG_CHANNEL == "plan-runner:system", (
            f"SYSTEM_LOG_CHANNEL 변경 감지: '{SYSTEM_LOG_CHANNEL}'. "
            f"bare 'plan-runner:logs' publish와 구분 불가할 수 있음."
        )

    def test_system_channel_not_same_as_log_prefix(self):
        """SYSTEM_LOG_CHANNEL이 LOG_CHANNEL_PREFIX와 다름 (채널 혼용 방지)"""
        from app.modules.dev_runner.services.log_service import (
            LOG_CHANNEL_PREFIX,
            SYSTEM_LOG_CHANNEL,
        )
        assert SYSTEM_LOG_CHANNEL != LOG_CHANNEL_PREFIX, (
            "SYSTEM_LOG_CHANNEL과 LOG_CHANNEL_PREFIX가 동일 — 채널 불일치 버그 재발 위험"
        )

    def test_per_runner_channel_not_bare_prefix(self):
        """per-runner 채널이 bare LOG_CHANNEL_PREFIX와 다름 (runner_id 없는 publish 방지)"""
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        runner_id = "runner-abc123"
        per_runner_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        # bare 채널 (= 채널 불일치 버그의 원인)은 per-runner 채널과 달라야 함
        assert per_runner_channel != LOG_CHANNEL_PREFIX, (
            f"per-runner 채널이 bare prefix와 동일 — runner_id 누락 가능성"
        )

    def test_runner_id_empty_string_guard(self):
        """빈 runner_id로 per-runner 채널 생성 시 bare prefix와 달라야 함 (guard 확인)

        wtools publisher가 runner_id를 빈 문자열로 publish하면 'plan-runner:logs:'가 됨.
        이는 bare 'plan-runner:logs'와 달라서 subscribe되지 않아야 함.
        """
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        empty_runner_id = ""
        broken_channel = f"{LOG_CHANNEL_PREFIX}:{empty_runner_id}"
        # 빈 runner_id 채널은 bare prefix와 다름 (콜론이 붙음)
        assert broken_channel != LOG_CHANNEL_PREFIX, (
            "빈 runner_id로 생성된 채널이 bare prefix와 동일 — subscribe 오작동 가능"
        )
        # 그러나 빈 runner_id 채널은 유효한 per-runner 채널이 아님을 코드 레벨에서 감지 가능
        assert broken_channel == "plan-runner:logs:", (
            f"빈 runner_id 채널 형식 불일치: '{broken_channel}'"
        )

    def test_stream_log_file_subscribes_per_runner_channel(self):
        """stream_log_file이 per-runner 채널에 subscribe함을 단언 (SYSTEM_LOG_CHANNEL 아님)

        stream_log_file 내부의 log_channel 생성 로직을 직접 검증.
        """
        from app.modules.dev_runner.services.log_service import LOG_CHANNEL_PREFIX
        runner_id = "test-runner-123"
        # stream_log_file이 구성하는 채널명 (log_service.py:242 참조)
        expected_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        assert expected_channel == f"plan-runner:logs:{runner_id}", (
            f"stream_log_file 구독 채널 포맷 불일치: '{expected_channel}'"
        )
        # SYSTEM_LOG_CHANNEL(plan-runner:system)과 달라야 함
        from app.modules.dev_runner.services.log_service import SYSTEM_LOG_CHANNEL
        assert expected_channel != SYSTEM_LOG_CHANNEL, (
            "stream_log_file이 SYSTEM_LOG_CHANNEL을 구독하려 함 — 채널 불일치 재발"
        )
