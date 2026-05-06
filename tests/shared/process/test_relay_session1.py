from unittest.mock import MagicMock

import pytest

from app.shared.process import relay


@pytest.mark.asyncio
async def test_relay_open_app_session1_runs_direct_popen(monkeypatch):
    monkeypatch.setattr(relay.session, "is_session_0", lambda: False)
    mock_popen = MagicMock()
    monkeypatch.setattr(relay.subprocess, "Popen", mock_popen)

    result = await relay.relay_open_app("explorer", ["D:\\work"])

    assert result == {"via": "direct", "app": "explorer"}
    mock_popen.assert_called_once()
    assert mock_popen.call_args.args[0] == ["explorer", "D:\\work"]


@pytest.mark.asyncio
async def test_relay_open_app_rejects_unknown_app(monkeypatch):
    monkeypatch.setattr(relay.session, "is_session_0", lambda: False)
    mock_popen = MagicMock()
    monkeypatch.setattr(relay.subprocess, "Popen", mock_popen)

    with pytest.raises(relay.OpenAppRelayError):
        await relay.relay_open_app("powershell", ["D:\\work"])

    mock_popen.assert_not_called()
