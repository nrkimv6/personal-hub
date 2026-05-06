from unittest.mock import MagicMock

import pytest

from app.modules.file_search.services import search_service


def test_search_service_open_file_session0_rejects_direct_launch(monkeypatch):
    service = search_service.SearchService()
    monkeypatch.setattr(search_service, "is_session_0", lambda: True)
    popen_mock = MagicMock()
    startfile_mock = MagicMock()
    monkeypatch.setattr(search_service.subprocess, "Popen", popen_mock)
    monkeypatch.setattr(search_service.os, "startfile", startfile_mock, raising=False)

    with pytest.raises(RuntimeError, match="Session 0"):
        service.open_file("D:\\work\\file.py", 10)

    popen_mock.assert_not_called()
    startfile_mock.assert_not_called()
