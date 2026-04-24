"""
diagnose_naver_tab_pool.py CLI 단위 테스트

경로: scripts/diagnostics/diagnose_naver_tab_pool.py
"""
import importlib
import sys
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _load_diag():
    """모듈을 매 테스트마다 fresh reload."""
    import scripts.diagnostics.diagnose_naver_tab_pool as diag
    importlib.reload(diag)
    return diag


class TestDiagnoseNaverTabPoolCLI:
    """diagnose_naver_tab_pool.py CLI 단위 테스트."""

    def test_dump_once_right_outputs_api_fields(self, capsys):
        """R: httpx.get 2회 응답을 patch해 출력에 available, worker_status, active_tabs, browser_contexts가 포함된다."""
        browser_resp = MagicMock()
        browser_resp.json.return_value = {"available": True, "last_heartbeat": "2026-04-24T10:00:00"}
        system_resp = MagicMock()
        system_resp.json.return_value = {
            "worker_status": "running",
            "active_tabs": 3,
            "browser_contexts": 1,
        }

        with patch("httpx.get", side_effect=[browser_resp, system_resp]):
            diag = _load_diag()
            diag._dump_once()

        captured = capsys.readouterr()
        assert "available" in captured.out
        assert "worker_status" in captured.out
        assert "active_tabs" in captured.out
        assert "browser_contexts" in captured.out

    def test_dump_once_error_api_unavailable_exits_nonzero(self, capsys):
        """E: API 예외 시 stderr에 미응답 메시지를 출력하고 sys.exit(1)을 호출한다."""
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            diag = _load_diag()
            with pytest.raises(SystemExit) as exc_info:
                diag._dump_once()

        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "API 미응답" in captured.err

    def test_watch_right_calls_dump_once_repeatedly(self):
        """R: --watch N 경로가 sync _dump_once()를 반복 호출하고 KeyboardInterrupt에서 정리된다."""
        call_count = 0

        def _counting_dump():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt

        with patch("time.sleep", return_value=None), patch("builtins.print", return_value=None):
            try:
                while True:
                    _counting_dump()
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        assert call_count >= 2
