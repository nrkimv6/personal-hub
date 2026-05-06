from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.image_classifier.routers import files


@pytest.mark.asyncio
async def test_open_local_file_uses_relay_not_direct_popen(tmp_path, monkeypatch):
    target = tmp_path / "image.png"
    target.write_text("x")

    relay_mock = AsyncMock(return_value={"via": "redis", "app": "explorer"})
    popen_mock = MagicMock()
    monkeypatch.setattr(files, "relay_open_app", relay_mock)
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    result = await files.open_local_file_or_folder(files.OpenLocalRequest(path=str(target)), db=MagicMock())

    assert result == {"status": "ok", "opened": str(target)}
    relay_mock.assert_awaited_once_with("explorer", ["/select,", str(target)])
    popen_mock.assert_not_called()


@pytest.mark.asyncio
async def test_open_folder_uses_relay_not_direct_popen(tmp_path, monkeypatch):
    target = tmp_path / "image.png"
    target.write_text("x")

    db = MagicMock()
    db.execute.return_value.fetchone.return_value = SimpleNamespace(file_path=str(target))
    relay_mock = AsyncMock(return_value={"via": "redis", "app": "explorer"})
    popen_mock = MagicMock()
    monkeypatch.setattr(files.settings, "SCAN_ROOT_FOLDERS", [], raising=False)
    monkeypatch.setattr(files, "relay_open_app", relay_mock)
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    result = await files.open_folder_in_explorer(files.OpenFolderRequest(file_id=1), db=db)

    assert result["status"] == "ok"
    relay_mock.assert_awaited_once_with("explorer", ["/select,", str(target)])
    popen_mock.assert_not_called()
