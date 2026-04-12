"""event_routing 단위 테스트

classify_key, extract_runner_id, extract_runner_id_from_channel 순수 함수 검증.
Redis 불필요 — 인자/반환값만 검증.
"""

import pytest

from app.modules.dev_runner.services.event_routing import (
    classify_key,
    extract_runner_id,
    extract_runner_id_from_channel,
    RUNNER_KEY_PREFIX,
    REDIS_STATE_KEY,
)


# ─── classify_key 테스트 ─────────────────────────────────────────────────────

class TestClassifyKey:
    def test_status_key(self):
        key = f"{RUNNER_KEY_PREFIX}:abc123:status"
        assert classify_key(key) == "status"

    def test_tracking_key(self):
        key = f"{REDIS_STATE_KEY}:current_task_text"
        assert classify_key(key) == "tracking"

    def test_plan_changed_key(self):
        key = f"{REDIS_STATE_KEY}:current_task_plan_file"
        assert classify_key(key) == "plan_changed"

    def test_unknown_key_returns_none(self):
        assert classify_key("unrelated:key") is None
        assert classify_key("plan-runner:listener:heartbeat") is None

    def test_active_runners_key_not_matched(self):
        key = "plan-runner:active_runners"
        result = classify_key(key)
        assert result is None

    def test_runner_key_various_fields(self):
        for field in ("status", "pid", "current_cycle", "start_time"):
            result = classify_key(f"{RUNNER_KEY_PREFIX}:runner01:{field}")
            assert result == "status", f"field={field!r}가 status로 매핑되어야 함"

    def test_empty_key_returns_none(self):
        assert classify_key("") is None

    def test_tracking_key_confidence(self):
        """B: current_task_confidence 키는 classify_key에 매핑 없음 → None 반환"""
        key = f"{REDIS_STATE_KEY}:current_task_confidence"
        assert classify_key(key) is None

    def test_plan_changed_requires_plan_file_suffix(self):
        key = f"{REDIS_STATE_KEY}:current_task_plan_file"
        assert classify_key(key) == "plan_changed"


# ─── extract_runner_id_from_channel 테스트 ───────────────────────────────────

class TestExtractRunnerIdFromChannel:
    def test_extract_runner_id_from_channel_right(self):
        """R: 정상 로그 채널 → runner_id 반환"""
        result = extract_runner_id_from_channel("plan-runner:logs:abc123")
        assert result == "abc123"

    def test_extract_runner_id_from_channel_merge(self):
        """R: 머지 로그 채널 → runner_id 반환"""
        result = extract_runner_id_from_channel("plan-runner:merge-log:def456")
        assert result == "def456"

    def test_extract_runner_id_from_channel_boundary_empty(self):
        """B: 빈 문자열 및 콜론 없는 문자열 → None 반환"""
        assert extract_runner_id_from_channel("") is None
        assert extract_runner_id_from_channel("nocolon") is None

    def test_extract_runner_id_from_channel_boundary_trailing_colon(self):
        """B: 콜론으로 끝나는 채널 (runner_id 빈값) → None 반환"""
        result = extract_runner_id_from_channel("plan-runner:logs:")
        assert result is None
