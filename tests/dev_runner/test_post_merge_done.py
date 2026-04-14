"""
TC: post-merge 자동 done 처리 단위 테스트

Phase T1: get_plan_completion / _call_done_api 검증
- test_get_plan_completion_all_done_R
- test_get_plan_completion_partial_R
- test_get_plan_completion_codeblock_excluded_B
- test_get_plan_completion_none_input_B
- test_get_plan_completion_missing_file_E
- test_call_done_api_success_R
- test_call_done_api_http_error_E
- test_call_done_api_connection_error_E
- test_call_done_api_success_false_body_E
- test_call_done_api_uses_base64_encoded_path_Co
"""
import base64
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# plan_worktree_helpers는 직접 import
from plan_worktree_helpers import get_plan_completion

# listener 로드용 mock
_SCRIPT_PATH = _SCRIPTS_DIR / "plan_runner" / "dev-runner-command-listener.py"
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_done", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cl():
    return _load_listener()


# ── get_plan_completion 테스트 ──────────────────────────────────


def test_get_plan_completion_all_done_R(tmp_path):
    """R: 전체 [x] 파일 → (N, N) 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 항목1\n- [x] 항목2\n- [x] 항목3\n", encoding="utf-8")
    assert get_plan_completion(str(plan)) == (3, 3)


def test_get_plan_completion_partial_R(tmp_path):
    """R: 일부 완료 → (done, total) 정확히 반환"""
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] 완료\n- [ ] 미완료1\n- [ ] 미완료2\n", encoding="utf-8")
    assert get_plan_completion(str(plan)) == (1, 3)


def test_get_plan_completion_codeblock_excluded_B(tmp_path):
    """B: 코드블럭 내 체크박스는 카운트 제외"""
    plan = tmp_path / "plan.md"
    plan.write_text(
        "- [x] 실제 완료\n"
        "```\n"
        "- [ ] 코드블럭 내부\n"
        "- [x] 코드블럭 내부2\n"
        "```\n"
        "- [ ] 실제 미완료\n",
        encoding="utf-8",
    )
    assert get_plan_completion(str(plan)) == (1, 2)


def test_get_plan_completion_none_input_B():
    """B: plan_file=None → (0, 0) 반환, 예외 없음"""
    assert get_plan_completion(None) == (0, 0)


def test_get_plan_completion_missing_file_E(tmp_path):
    """E: 존재하지 않는 파일 → (0, 0) 반환"""
    assert get_plan_completion(str(tmp_path / "nonexistent.md")) == (0, 0)


# ── _call_done_api 테스트 ──────────────────────────────────────


def test_call_done_api_success_R(cl):
    """R: requests.post 200 응답 → True 반환"""
    pub_calls = []
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}

    with patch("requests.post", return_value=mock_resp):
        result = cl._call_done_api("/some/plan.md", "runner1", pub_calls.append)

    assert result is True
    assert len(pub_calls) == 0  # 성공 시 pub 없음


def test_call_done_api_http_error_E(cl):
    """E: 500 응답 → False 반환, pub_fn 호출됨"""
    pub_calls = []
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("requests.post", return_value=mock_resp):
        result = cl._call_done_api("/some/plan.md", "runner1", pub_calls.append)

    assert result is False
    assert any("done API 실패" in m for m in pub_calls)


def test_call_done_api_connection_error_E(cl):
    """E: ConnectionError → False 반환, pub_fn 호출됨"""
    import requests as _requests

    pub_calls = []

    with patch("requests.post", side_effect=_requests.exceptions.ConnectionError("refused")):
        result = cl._call_done_api("/some/plan.md", "runner1", pub_calls.append)

    assert result is False
    assert any("연결 실패" in m for m in pub_calls)


def test_call_done_api_success_false_body_E(cl):
    """E: 200 + success=false 응답 → False 반환, pub_fn 호출됨"""
    pub_calls = []
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": False, "message": "archive target resolve failed"}

    with patch("requests.post", return_value=mock_resp):
        result = cl._call_done_api("/some/plan.md", "runner1", pub_calls.append)

    assert result is False
    assert any("success=false" in m for m in pub_calls)


def test_call_done_api_uses_base64_encoded_path_Co(cl):
    """Co: done API 호출 URL이 base64 encoded_path 규약을 사용한다."""
    pub_calls = []
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True}
    plan_path = "/some/path/with space/plan.md"

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = cl._call_done_api(plan_path, "runner1", pub_calls.append)

    assert result is True
    called_url = mock_post.call_args[0][0]
    assert mock_post.call_args.kwargs.get("headers") == {"X-Plan-Runner-Id": "runner1"}
    encoded = called_url.split("/plans/")[1].split("/done")[0]
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    assert decoded == plan_path
