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
    async def timeout_without_await_leak(awaitable, *, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    fake_cli_path = Path(r"D:\work\project\tools\kakaocli-win\.venv\Scripts\kakaocli-win.exe")
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.wait = AsyncMock()
    proc.kill = MagicMock()
    proc.returncode = 0

    with patch.object(listener, "_get_cli_path", return_value=fake_cli_path), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)), \
         patch("asyncio.wait_for", side_effect=timeout_without_await_leak):
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


def test_input_guard_acquire_release_writes_state(listener, tmp_path):
    state_file = tmp_path / "kakao_guard_state.json"

    with patch.object(listener, "GUARD_STATE_FILE", state_file), \
         patch.object(listener, "_block_input", side_effect=[True, True]):
        with listener.KakaoInputGuard(enabled=True, timeout_seconds=5, abort_on_remote_session=True):
            assert state_file.exists()

    state = state_file.read_text(encoding="utf-8")
    assert '"state": "released"' in state


@pytest.mark.asyncio
async def test_guard_failure_requeues_without_cli(listener):
    queue = MagicMock()
    queue.requeue = AsyncMock(return_value=True)
    queue.dead_letter = AsyncMock(return_value=True)
    queue.client.set = AsyncMock(return_value=True)

    payload = {
        "id": "payload-guard",
        "room_name": "소나무봇",
        "message": "메시지",
        "metadata": {"retry_count": 0, "guard_required": True},
    }

    with patch.object(listener, "is_payload_expired", return_value=False), \
         patch.object(listener, "_get_setting", side_effect=lambda name, default: {
             "MEGABEAUTY_KAKAO_INPUT_GUARD_ENABLED": True,
             "MEGABEAUTY_KAKAO_INPUT_GUARD_TIMEOUT_SECONDS": 5,
             "MEGABEAUTY_KAKAO_INPUT_GUARD_ABORT_ON_REMOTE_SESSION": True,
             "MEGABEAUTY_KAKAO_INPUT_GUARD_MAX_RETRIES": 3,
         }.get(name, default)), \
         patch.object(listener, "_preflight_kakao_room", return_value=listener.SendResult(True)), \
         patch.object(listener, "_block_input", return_value=False), \
         patch.object(listener, "_send_via_cli_raw", new=AsyncMock()) as mock_send:
        await listener._process_payload(payload, queue)

    mock_send.assert_not_called()
    queue.requeue.assert_awaited_once()
    queue.dead_letter.assert_not_called()
    requeue_kwargs = queue.requeue.await_args.kwargs
    assert "BlockInput acquire failed" in requeue_kwargs["last_error"]


@pytest.mark.asyncio
async def test_retry_exceeded_goes_to_dead_letter(listener):
    queue = MagicMock()
    queue.requeue = AsyncMock(return_value=True)
    queue.dead_letter = AsyncMock(return_value=True)
    queue.client.set = AsyncMock(return_value=False)

    payload = {
        "id": "payload-dead",
        "room_name": "소나무봇",
        "message": "메시지",
        "metadata": {"retry_count": 3, "guard_required": True},
    }

    with patch.object(listener, "is_payload_expired", return_value=False), \
         patch.object(listener, "_get_setting", side_effect=lambda name, default: {
             "MEGABEAUTY_KAKAO_INPUT_GUARD_MAX_RETRIES": 3,
         }.get(name, default)), \
         patch.object(
             listener,
             "_send_via_cli_guarded",
             new=AsyncMock(return_value=listener.SendResult(False, retryable=True, error="timeout")),
         ):
        await listener._process_payload(payload, queue)

    queue.requeue.assert_not_called()
    queue.dead_letter.assert_awaited_once()
    assert queue.dead_letter.await_args.kwargs["last_error"] == "timeout"


@pytest.mark.asyncio
async def test_fake_cli_guard_order(listener):
    events = []

    class FakeGuard:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            events.append("guard_acquire")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("guard_release")

    async def fake_send(room_name, message, *, timeout_seconds):
        events.append("cli_send")
        return listener.SendResult(True)

    with patch.object(listener, "_get_setting", side_effect=lambda name, default: {
             "MEGABEAUTY_KAKAO_INPUT_GUARD_ENABLED": True,
             "MEGABEAUTY_KAKAO_INPUT_GUARD_TIMEOUT_SECONDS": 5,
             "MEGABEAUTY_KAKAO_INPUT_GUARD_ABORT_ON_REMOTE_SESSION": True,
         }.get(name, default)), \
         patch.object(listener, "_preflight_kakao_room", return_value=listener.SendResult(True)), \
         patch.object(listener, "KakaoInputGuard", FakeGuard), \
         patch.object(listener, "_send_via_cli_raw", side_effect=fake_send):
        result = await listener._send_via_cli_guarded("소나무봇", "메시지", guard_required=True)

    assert result.success is True
    assert events == ["guard_acquire", "cli_send", "guard_release"]
