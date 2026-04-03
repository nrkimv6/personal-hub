from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

from app.modules.slide_scanner.services.rectifier_client import RectifierClient
from app.modules.slide_scanner.config import settings

rectifier_client_module = importlib.import_module("app.modules.slide_scanner.services.rectifier_client")


def _prepare_rectifier_paths(tmp_path: Path, monkeypatch):
    root = tmp_path / "slide-rectifier"
    root.mkdir(parents=True, exist_ok=True)
    python_exe = root / "python.exe"
    python_exe.write_bytes(b"")

    monkeypatch.setattr(settings, "RECTIFIER_ROOT", root)
    monkeypatch.setattr(settings, "RECTIFIER_PYTHON", python_exe)


def test_detect_uses_dl_engine_when_configured(tmp_path: Path, monkeypatch):
    _prepare_rectifier_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "dl")

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout='[{"x": 1, "y": 1}, {"x": 9, "y": 1}, {"x": 9, "y": 9}, {"x": 1, "y": 9}]',
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    points = client.detect(Path(r"D:\images\sample.jpg"))

    assert points == [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]
    command = captured["command"]
    assert command[:3] == [str(settings.RECTIFIER_PYTHON), "-m", "slide_rectifier"]
    assert "--engine" in command
    assert "dl" in command


def test_detect_falls_back_to_opencv_for_unknown_engine(tmp_path: Path, monkeypatch):
    _prepare_rectifier_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "not-supported")

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(
            returncode=0,
            stdout='[{"x": 1, "y": 1}, {"x": 9, "y": 1}, {"x": 9, "y": 9}, {"x": 1, "y": 9}]',
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    client.detect(Path(r"D:\images\sample.jpg"))
    command = captured["command"]
    engine_index = command.index("--engine") + 1
    assert command[engine_index] == "opencv"
