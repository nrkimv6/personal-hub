"""is_visible_runner() 단위 테스트 (RIGHT-BICEP)

visibility.py의 단일 진실 원천 함수를 검증한다.
화이트리스트 방식: "user" / "user:all" trigger만 visible=True.
"""

import pytest
from app.modules.dev_runner.services.visibility import is_visible_runner


class TestIsVisibleRunner:
    # ── R: Right (정상 케이스) ───────────────────────────────────────────────

    def test_trigger_user_returns_true(self):
        """R: trigger="user", 일반 runner_id → True"""
        assert is_visible_runner("user", "abc12345") is True

    def test_trigger_user_all_returns_true(self):
        """R: trigger="user:all", 일반 runner_id → True"""
        assert is_visible_runner("user:all", "abc12345") is True

    def test_trigger_tc_returns_false(self):
        """R: trigger="tc:test" → False (테스트 러너)"""
        assert is_visible_runner("tc:test", "abc12345") is False

    def test_trigger_api_returns_false(self):
        """R: trigger="api" → False (API 직접 실행)"""
        assert is_visible_runner("api", "abc12345") is False

    def test_normal_id_with_user_trigger(self):
        """R: 일반 hex runner_id + trigger="user" → True"""
        assert is_visible_runner("user", "a1b2c3d4") is True

    # ── B: Boundary (경계 케이스) ────────────────────────────────────────────

    def test_trigger_none_returns_false(self):
        """B: trigger=None (Redis 키 미설정) → False"""
        assert is_visible_runner(None, "abc12345") is False

    def test_trigger_empty_returns_false(self):
        """B: trigger="" (빈 문자열) → False"""
        assert is_visible_runner("", "abc12345") is False

    def test_trigger_manual_returns_false(self):
        """B: trigger="manual" → False (화이트리스트에 없는 임의 값)"""
        assert is_visible_runner("manual", "abc12345") is False

    def test_t_prefix_runner_id_with_tc_trigger(self):
        """B: runner_id="t-test-abcd" (pytest 생성 패턴) + trigger="tc:test" → False"""
        assert is_visible_runner("tc:test", "t-test-abcd") is False

    def test_user_trigger_substring_not_matched(self):
        """B: trigger="user_extra" → False (정확히 "user"만 허용)"""
        assert is_visible_runner("user_extra", "abc12345") is False

    def test_user_all_trigger_substring_not_matched(self):
        """B: trigger="user:all:extra" → False (정확히 "user:all"만 허용)"""
        assert is_visible_runner("user:all:extra", "abc12345") is False

    # ── E: Error (이중 방어) ─────────────────────────────────────────────────

    def test_tc_pytest_prefix_always_false_even_with_user_trigger(self):
        """E: runner_id="tc-pytest-abc", trigger="user" → False (이중 방어 — tc-pytest- 접두사)"""
        assert is_visible_runner("user", "tc-pytest-abc123") is False

    def test_tc_pytest_prefix_with_user_all_also_false(self):
        """E: runner_id="tc-pytest-xyz", trigger="user:all" → False (이중 방어)"""
        assert is_visible_runner("user:all", "tc-pytest-xyz") is False

    def test_tc_pytest_prefix_with_none_trigger_false(self):
        """E: runner_id="tc-pytest-xxx", trigger=None → False"""
        assert is_visible_runner(None, "tc-pytest-xxx") is False
