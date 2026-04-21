"""
Phase T5: v2 done 전이 HTTP 통합 테스트

TestClient 기반 — 실서버 불필요.
plan-runner의 done 경로 변경이 admin API를 통해 간접 실행되므로 T5 필수.

fix: v2-pipeline-transition-safety
"""
import base64
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

pytestmark = pytest.mark.http


class TestT5DoneApiFromLoop:
    """32. done API 정상 호출 — loop auto-done 후 plan archived 확인"""

    def test_T5_done_api_called_from_loop(self, tmp_path):
        """_handle_post_merge_done → 완료율 100% → _call_done_api 호출 확인"""
        from _dr_merge import _handle_post_merge_done

        plan_file = tmp_path / "test_done_api.md"
        plan_file.write_text(
            "# Test\n> 상태: 머지대기\n> 진행률: 2/2 (100%)\n\n- [x] t1\n- [x] t2\n",
            encoding="utf-8",
        )
        pub_fn = MagicMock()
        mock_rc = MagicMock()

        with patch("_dr_merge._call_done_api", return_value={"success": True, "reason": None, "message": ""}) as mock_api:
            _handle_post_merge_done(str(plan_file), "t5-runner", pub_fn, mock_rc)
            mock_api.assert_called_once()

        # plan 상태가 구현완료로 전이됐는지 확인
        text = plan_file.read_text(encoding="utf-8")
        assert re.search(r">\s*상태:\s*구현완료", text), f"상태 전이 안 됨: {text[:200]}"


class TestT5DoneApiNotDoubleCalled:
    """33. done_completed 설정 후 fallback에서 done API 미호출"""

    def test_T5_done_api_not_double_called(self, tmp_path):
        """done_completed=1 → detect None → _handle_post_merge_done 미실행"""
        from _dr_merge import detect_merged_but_not_done

        runner_id = "t5-no-double"
        plan_file = tmp_path / "test_no_double.md"
        plan_file.write_text("> 상태: 머지대기\n- [x] t1\n", encoding="utf-8")

        mock_rc = MagicMock()
        mock_rc.get.side_effect = lambda k: {
            f"plan-runner:runners:{runner_id}:done_completed": "1",
            f"plan-runner:runners:{runner_id}:plan_file": str(plan_file),
            f"plan-runner:runners:{runner_id}:branch": "impl/test",
            f"plan-runner:runners:{runner_id}:merge_status": "merged",
        }.get(k)

        result = detect_merged_but_not_done(runner_id, mock_rc)
        assert result is None, "done_completed=1인데 fallback 감지됨"


class TestT5NoDoneOnMergeFailure:
    """34. merge 실패 시 done API 미호출"""

    def test_T5_no_done_on_merge_failure(self, tmp_path):
        """merge_status='error' → redis_merged=False, git_merged=False → detect None → done 미호출"""
        from _dr_merge import detect_merged_but_not_done

        runner_id = "t5-merge-fail"
        plan_file = tmp_path / "test_merge_fail.md"
        plan_file.write_text("> 상태: 머지대기\n- [x] t1\n", encoding="utf-8")

        mock_rc = MagicMock()
        mock_rc.get.side_effect = lambda k: {
            f"plan-runner:runners:{runner_id}:done_completed": None,
            f"plan-runner:runners:{runner_id}:plan_file": str(plan_file),
            f"plan-runner:runners:{runner_id}:branch": "impl/test",
            f"plan-runner:runners:{runner_id}:merge_status": "error",
        }.get(k)

        # git log에서도 merge 감지 안 되도록 mock
        with patch("_dr_merge.subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=1, stdout="")
            result = detect_merged_but_not_done(runner_id, mock_rc)
            assert result is None, f"merge 실패인데 감지됨: {result}"


class TestT5DoneApiContract:
    """35. done API 호출 계약(base64 경로 + success=false 처리)"""

    def test_T5_done_api_uses_base64_path(self):
        from _dr_merge import _call_done_api

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        plan_path = "/tmp/v2 done plan.md"

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = _call_done_api(plan_path, "t5-contract", lambda _m: None)

        assert result["success"] is True
        assert result["reason"] is None
        called_url = mock_post.call_args[0][0]
        encoded = called_url.split("/plans/")[1].split("/done")[0]
        padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        assert decoded == plan_path

    def test_T5_done_api_success_false_body_returns_false(self):
        from _dr_merge import _call_done_api

        messages = []
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": False, "message": "archive target resolve failed"}

        with patch("requests.post", return_value=mock_resp):
            result = _call_done_api("/tmp/plan.md", "t5-contract", messages.append)

        assert result["success"] is False
        assert result["reason"] == "done_api_failed"
        assert "archive target resolve failed" in result["message"]
        assert any("success=false" in m for m in messages)
