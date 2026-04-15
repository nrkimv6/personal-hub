"""kakao-notification-listener.py 단위 테스트."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "services" / "kakao-notification-listener.py"


@pytest.fixture(scope="module")
def listener():
    """kakao-notification-listener 스크립트를 동적 로드한다."""
    spec = importlib.util.spec_from_file_location("kakao_notification_listener", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_send_via_cli_invokes_kakaocli_with_room_and_message(listener):
    fake_cli_path = Path(r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe")
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"ok", b""))
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    proc.returncode = 0

    with patch.object(listener, "_get_cli_path", return_value=fake_cli_path), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)) as mock_exec:
        result = await listener._send_via_cli("소나무봇", "메가뷰티쇼 공석 알림")

    assert result is True
    mock_exec.assert_awaited_once()
    call_args = mock_exec.call_args
    assert call_args.args[:4] == (
        str(fake_cli_path),
        "send",
        "소나무봇",
        "메가뷰티쇼 공석 알림",
    )
    assert call_args.kwargs["cwd"] == str(fake_cli_path.parents[2])


@pytest.mark.asyncio
async def test_send_via_cli_missing_exe_returns_false(listener):
    fake_cli_path = MagicMock(spec=Path)
    fake_cli_path.exists.return_value = False

    with patch.object(listener, "_get_cli_path", return_value=fake_cli_path), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
        result = await listener._send_via_cli("소나무봇", "메시지")

    assert result is False
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_send_via_cli_timeout_kills_process(listener):
    fake_cli_path = Path(r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe")
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    proc.returncode = 0

    with patch.object(listener, "_get_cli_path", return_value=fake_cli_path), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)), \
         patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await listener._send_via_cli("소나무봇", "메시지")

    assert result is False
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_payload_drops_expired_message(listener):
    with patch.object(listener, "is_payload_expired", return_value=True):
        await listener._process_payload(
            {
                "id": "payload-1",
                "room_name": "소나무봇",
                "message": "만료",
                "expires_at": "2026-04-15T10:00:00",
            }
        )
