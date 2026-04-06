"""
TC: visibility 계약 동일성 검증 (Phase T1 #15 / Phase 5 #11)

app의 is_visible_runner와 scripts의 _is_user_visible_trigger가
동일 입력에 동일 결과를 반환하는지 검증한다.
"""
import sys
import types
from pathlib import Path

import pytest

# scripts 환경 경로 추가
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# scripts 환경 의존성 mock
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _mock_noise)

from app.modules.dev_runner.services.visibility import is_visible_runner
from _dr_runner_predicates import _is_user_visible_trigger


# 테스트 입력 매트릭스
TRIGGERS = ["user", "user:all", "tc:xxx", None, "", "api", "manual"]
RUNNER_IDS = ["tc-pytest-001", "t-xxx", "test_xxx", "abc12345", "", "dm-abc123", "normal-runner"]


@pytest.mark.parametrize("trigger", TRIGGERS)
@pytest.mark.parametrize("runner_id", RUNNER_IDS)
def test_visibility_contract(trigger, runner_id):
    """is_visible_runner와 _is_user_visible_trigger가 동일 결과 반환"""
    app_result = is_visible_runner(trigger, runner_id)
    scripts_result = _is_user_visible_trigger(trigger, runner_id)
    assert app_result == scripts_result, (
        f"visibility mismatch: trigger={trigger!r}, runner_id={runner_id!r}\n"
        f"  is_visible_runner={app_result}, _is_user_visible_trigger={scripts_result}"
    )


class TestVisibilityDetails:
    """개별 케이스 명시 검증"""

    def test_tc_pytest_prefix_always_hidden(self):
        """tc-pytest- 접두사 runner는 trigger 관계없이 항상 숨김"""
        for trigger in ["user", "user:all", None, ""]:
            assert is_visible_runner(trigger, "tc-pytest-001") is False
            assert _is_user_visible_trigger(trigger, "tc-pytest-001") is False

    def test_user_trigger_visible(self):
        """trigger=user, 일반 runner_id → visible"""
        assert is_visible_runner("user", "abc12345") is True
        assert _is_user_visible_trigger("user", "abc12345") is True

    def test_user_all_trigger_visible(self):
        """trigger=user:all, 일반 runner_id → visible"""
        assert is_visible_runner("user:all", "abc12345") is True
        assert _is_user_visible_trigger("user:all", "abc12345") is True

    def test_none_trigger_hidden(self):
        """trigger=None → 항상 숨김"""
        assert is_visible_runner(None, "abc12345") is False
        assert _is_user_visible_trigger(None, "abc12345") is False

    def test_api_trigger_hidden(self):
        """trigger=api → 숨김"""
        assert is_visible_runner("api", "abc12345") is False
        assert _is_user_visible_trigger("api", "abc12345") is False

    def test_t_prefix_runner_id(self):
        """t- 접두사 runner_id는 t-xxx를 필터링하지 않아야 함 (tc-pytest-만 필터)"""
        # t-my-runner는 user trigger면 visible (기존 _dr_process_utils에서 잘못 필터했던 케이스)
        assert is_visible_runner("user", "t-my-runner") is True
        assert _is_user_visible_trigger("user", "t-my-runner") is True

    def test_test_prefix_runner_id(self):
        """test_ 접두사 runner_id는 필터링하지 않아야 함 (tc-pytest-만 필터)"""
        assert is_visible_runner("user", "test_my_plan") is True
        assert _is_user_visible_trigger("user", "test_my_plan") is True
