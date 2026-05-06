"""
Phase T5: HTTP API → browser_commands → worker 소비 경로 stage-aware timeout 계약 검증

TestClient 없이 worker._process_browser_commands()를 직접 호출하고 DB mock으로 검증.
실서버 불필요.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.shared.worker.exceptions import TabOperationTimeout
from app.worker.naver_monitor_worker import NaverMonitorWorker


def _pending_command(cmd_id: int = 1, service_account_id: int = 1) -> dict:
    return {
        "id": cmd_id,
        "command_type": "naver_check_login",
        "request_data": "{}",
        "service_account_id": service_account_id,
    }


def _make_db_mock(commands: list) -> MagicMock:
    """pending row를 fetchall로 반환하는 DB mock."""
    db = MagicMock()
    fetch_result = MagicMock()
    rows = [
        (c["id"], c["command_type"], c["request_data"], c["service_account_id"])
        for c in commands
    ]
    fetch_result.fetchall.return_value = rows
    db.execute.return_value = fetch_result
    return db


@pytest.mark.asyncio
@pytest.mark.http
async def test_http_check_login_command_timeout_persists_stage_acquire():
    """
    _process_browser_commands()가 TabOperationTimeout(stage=acquire, timeout=0.05) 수신 시
    DB row를 failed로 업데이트하고 error_message에 stage=acquire + timeout: 0.05s를 기록하는지 검증 (D3 계약)
    """
    worker = NaverMonitorWorker()
    worker.browser = MagicMock()  # browser 없으면 _process_browser_commands가 즉시 리턴
    cmd = _pending_command(cmd_id=42)
    timeout_err = TabOperationTimeout("탭 획득 타임아웃 (stage=acquire)", timeout=0.05)

    error_calls: list[dict] = []

    def capture_execute(sql_text, params=None):
        sql = str(sql_text)
        if "failed" in sql and params and "error" in params:
            error_calls.append(params)
        result = MagicMock()
        result.fetchall.return_value = [
            (cmd["id"], cmd["command_type"], cmd["request_data"], cmd["service_account_id"])
        ] if "pending" in sql else []
        return result

    db = MagicMock()
    db.execute.side_effect = capture_execute

    with patch("app.worker.naver_monitor_worker.SessionLocal", return_value=db), \
         patch.object(worker, "_execute_browser_command", side_effect=timeout_err):
        await worker._process_browser_commands()

    # failed 업데이트 호출 확인
    assert len(error_calls) == 1, f"failed 업데이트 호출 수: {len(error_calls)}"
    error_msg = str(error_calls[0].get("error", ""))
    assert "stage=acquire" in error_msg, f"error_message에 stage=acquire 없음: {error_msg!r}"
    assert "timeout: 0.05s" in error_msg, f"error_message에 timeout: 0.05s 없음: {error_msg!r}"


@pytest.mark.asyncio
@pytest.mark.http
async def test_http_check_login_command_success_still_completes():
    """
    _process_browser_commands()의 success case가 completed로 끝나는지 검증
    — D3 변경이 정상 경로를 깨지 않음을 확인
    """
    worker = NaverMonitorWorker()
    worker.browser = MagicMock()  # browser 없으면 _process_browser_commands가 즉시 리턴
    cmd = _pending_command(cmd_id=43)

    completed_calls: list[dict] = []

    def capture_execute(sql_text, params=None):
        sql = str(sql_text)
        if "completed" in sql and params and "result" in params:
            completed_calls.append(params)
        result = MagicMock()
        result.fetchall.return_value = [
            (cmd["id"], cmd["command_type"], cmd["request_data"], cmd["service_account_id"])
        ] if "pending" in sql else []
        return result

    db = MagicMock()
    db.execute.side_effect = capture_execute

    with patch("app.worker.naver_monitor_worker.SessionLocal", return_value=db), \
         patch.object(worker, "_execute_browser_command", return_value={"status": "ok"}):
        await worker._process_browser_commands()

    assert len(completed_calls) == 1, f"completed 업데이트 호출 수: {len(completed_calls)}"
