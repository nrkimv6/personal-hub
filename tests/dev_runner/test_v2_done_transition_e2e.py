"""
Phase T4: v2 done 전이 E2E 테스트

done_completed 플래그에 의한 fallback 방지 + _handle_post_merge_done 멱등성 검증.
mock subprocess / mock Redis 사용, 실서버 불필요.

fix: v2-pipeline-transition-safety
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _mock_noise)

pytestmark = pytest.mark.e2e


class TestT4DoneCompletedFlagPrevents:
    """30. done_completed 플래그가 fallback을 방지하는지 E2E 검증"""

    def test_T4_done_completed_flag_prevents_fallback(self, tmp_path):
        """done_completed='1' → detect_merged_but_not_done None → _handle_post_merge_done 미호출"""
        from _dr_merge import detect_merged_but_not_done, is_done_completed

        runner_id = "t4-done-flag-test"
        plan_file = tmp_path / "test_plan.md"
        plan_file.write_text("> 상태: 머지대기\n- [x] task\n", encoding="utf-8")

        mock_rc = MagicMock()
        # done_completed=1 설정
        mock_rc.get.side_effect = lambda k: {
            f"plan-runner:runners:{runner_id}:done_completed": "1",
            f"plan-runner:runners:{runner_id}:plan_file": str(plan_file),
            f"plan-runner:runners:{runner_id}:branch": "impl/test",
            f"plan-runner:runners:{runner_id}:merge_status": "merged",
        }.get(k)

        # is_done_completed가 True
        assert is_done_completed(runner_id, mock_rc) is True

        # detect가 None 반환 (fallback 불필요)
        result = detect_merged_but_not_done(runner_id, mock_rc)
        assert result is None, f"done_completed=1인데 감지됨: {result}"


class TestT4PostMergeDoneIdempotent:
    """31. _handle_post_merge_done 멱등성 E2E 검증"""

    def test_T4_post_merge_done_missing_plan(self, tmp_path):
        """plan 파일 없는 상태 → _handle_post_merge_done 에러 없이 조기 반환"""
        from _dr_merge import _handle_post_merge_done

        runner_id = "t4-idempotent-test"
        nonexistent = str(tmp_path / "nonexistent_plan.md")
        pub_fn = MagicMock()
        mock_rc = MagicMock()

        # 예외 없이 실행 완료
        _handle_post_merge_done(nonexistent, runner_id, pub_fn, mock_rc)

        # "이미 처리됨" 메시지 확인
        called_args = [str(c) for c in pub_fn.call_args_list]
        assert any("처리됨" in a or "없음" in a for a in called_args), \
            f"조기 반환 메시지 없음: {called_args}"

    def test_T4_post_merge_done_already_completed(self, tmp_path):
        """plan 상태가 '완료' → done API 미호출"""
        from _dr_merge import _handle_post_merge_done

        runner_id = "t4-already-done"
        plan_file = tmp_path / "already_done.md"
        plan_file.write_text("> 상태: 완료\n- [x] task\n", encoding="utf-8")

        pub_fn = MagicMock()
        mock_rc = MagicMock()

        with patch("_dr_merge._call_done_api") as mock_done_api:
            _handle_post_merge_done(str(plan_file), runner_id, pub_fn, mock_rc)
            mock_done_api.assert_not_called()
