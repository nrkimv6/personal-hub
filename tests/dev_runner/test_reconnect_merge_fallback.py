"""
TC: _try_v2_merge_fallback 단위 테스트 (Phase T1)

Phase 1에서 추출한 merge fallback 공통 헬퍼 함수의 동작을 검증한다.
- R: detect → handle 순서 실행
- B: detect가 None 반환 시 handle 미호출
- E: detect 예외 시 False 반환
- E: handle 예외 시 False 반환 (cleanup 계속)
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# _dr_merge mock — scripts 환경에서 import 에러 방지
_mock_dr_merge = types.ModuleType("_dr_merge")
_mock_dr_merge.detect_merged_but_not_done = MagicMock(return_value=None)
_mock_dr_merge._handle_post_merge_done = MagicMock()
_mock_dr_merge._pub_and_log = MagicMock()
sys.modules.setdefault("_dr_merge", _mock_dr_merge)

# listener_noise_filter mock
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _mock_noise)


def _load_try_v2_merge_fallback():
    """_try_v2_merge_fallback 함수를 _dr_process_utils에서 로드"""
    import importlib
    import _dr_process_utils
    importlib.reload(_dr_process_utils)
    return _dr_process_utils._try_v2_merge_fallback


def _make_redis_mock():
    r = MagicMock()
    r.get.return_value = None
    return r


class TestTryV2MergeFallback:
    """_try_v2_merge_fallback 단위 테스트"""

    def test_try_merge_fallback_detect_then_handle(self):
        """R: detect 양성 → _handle_post_merge_done 호출, False 반환"""
        detect_result = {"plan_file": "/path/to/plan.md", "runner_id": "abc12345"}

        mock_detect = MagicMock(return_value=detect_result)
        mock_handle = MagicMock()
        mock_pub_log = MagicMock()

        mock_merge_mod = types.ModuleType("_dr_merge")
        mock_merge_mod.detect_merged_but_not_done = mock_detect
        mock_merge_mod._handle_post_merge_done = mock_handle
        mock_merge_mod._pub_and_log = mock_pub_log

        r = _make_redis_mock()
        runner_id = "abc12345"

        with patch.dict(sys.modules, {"_dr_merge": mock_merge_mod}):
            fn = _load_try_v2_merge_fallback()
            result = fn(runner_id, r, "test_reason")

        assert result is False  # 항상 False 반환
        mock_detect.assert_called_once_with(runner_id, r)
        mock_handle.assert_called_once()
        # _handle_post_merge_done 첫 번째 인자가 plan_file
        assert mock_handle.call_args[0][0] == "/path/to/plan.md"
        # 두 번째 인자가 runner_id
        assert mock_handle.call_args[0][1] == runner_id

    def test_try_merge_fallback_detect_returns_none(self):
        """B: detect가 None 반환 시 _handle_post_merge_done 미호출, False 반환"""
        mock_detect = MagicMock(return_value=None)
        mock_handle = MagicMock()
        mock_pub_log = MagicMock()

        mock_merge_mod = types.ModuleType("_dr_merge")
        mock_merge_mod.detect_merged_but_not_done = mock_detect
        mock_merge_mod._handle_post_merge_done = mock_handle
        mock_merge_mod._pub_and_log = mock_pub_log

        r = _make_redis_mock()
        runner_id = "abc12345"

        with patch.dict(sys.modules, {"_dr_merge": mock_merge_mod}):
            fn = _load_try_v2_merge_fallback()
            result = fn(runner_id, r, "test_reason")

        assert result is False
        mock_detect.assert_called_once()
        mock_handle.assert_not_called()

    def test_try_merge_fallback_detect_exception(self):
        """E: detect_merged_but_not_done 예외 시 False 반환 (cleanup 계속)"""
        mock_merge_mod = types.ModuleType("_dr_merge")
        mock_merge_mod.detect_merged_but_not_done = MagicMock(side_effect=RuntimeError("redis error"))
        mock_merge_mod._handle_post_merge_done = MagicMock()
        mock_merge_mod._pub_and_log = MagicMock()

        r = _make_redis_mock()
        runner_id = "abc12345"

        with patch.dict(sys.modules, {"_dr_merge": mock_merge_mod}):
            fn = _load_try_v2_merge_fallback()
            # 예외가 전파되지 않아야 함
            result = fn(runner_id, r, "test_reason")

        assert result is False
        mock_merge_mod._handle_post_merge_done.assert_not_called()

    def test_try_merge_fallback_handle_exception(self):
        """E: detect 성공 but _handle_post_merge_done 예외 시 warning 로그 후 False 반환"""
        detect_result = {"plan_file": "/path/to/plan.md", "runner_id": "abc12345"}

        mock_merge_mod = types.ModuleType("_dr_merge")
        mock_merge_mod.detect_merged_but_not_done = MagicMock(return_value=detect_result)
        mock_merge_mod._handle_post_merge_done = MagicMock(side_effect=ValueError("handle error"))
        mock_merge_mod._pub_and_log = MagicMock()

        r = _make_redis_mock()
        runner_id = "abc12345"

        with patch.dict(sys.modules, {"_dr_merge": mock_merge_mod}):
            fn = _load_try_v2_merge_fallback()
            # 예외가 전파되지 않아야 함
            result = fn(runner_id, r, "test_reason")

        assert result is False
        mock_merge_mod.detect_merged_but_not_done.assert_called_once()
        mock_merge_mod._handle_post_merge_done.assert_called_once()
