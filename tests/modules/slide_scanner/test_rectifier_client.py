from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services.rectifier_client import LEGACY_CLI_CONTRACT_REASON, RectifierClient

rectifier_client_module = importlib.import_module("app.modules.slide_scanner.services.rectifier_client")


def _prepare_rectifier_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "slide-rectifier"
    root.mkdir(parents=True, exist_ok=True)
    python_exe = root / "python.exe"
    python_exe.write_bytes(b"")

    monkeypatch.setattr(settings, "RECTIFIER_ROOT", root)
    monkeypatch.setattr(settings, "RECTIFIER_PYTHON", python_exe)


def test_detect_with_meta_right_object_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_rectifier_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "dl")

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"points":[{"x":1,"y":1},{"x":9,"y":1},{"x":9,"y":9},{"x":1,"y":9}],'
                '"meta":{"requested_engine":"dl","selected_engine":"opencv","confidence":0.77,'
                '"fallback_reason":"model_missing","selection_reason":"opencv_higher"}}'
            ),
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    result = client.detect_with_meta(Path(r"D:\images\sample.jpg"))

    command = captured["command"]
    assert command[:3] == [str(settings.RECTIFIER_PYTHON), "-m", "slide_rectifier"]
    assert "--engine" in command and "dl" in command
    assert "--with-meta" in command
    assert result["points"] == [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]
    assert result["meta"]["selected_engine"] == "opencv"
    assert result["meta"]["confidence"] == 0.77
    assert result["meta"]["fallback_reason"] == "model_missing"


def test_detect_with_meta_boundary_legacy_list_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_rectifier_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "opencv")

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='[{"x":1,"y":1},{"x":9,"y":1},{"x":9,"y":9},{"x":1,"y":9}]',
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    result = client.detect_with_meta(Path(r"D:\images\sample.jpg"))
    assert result["points"] == [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]
    assert result["meta"]["fallback_reason"] == LEGACY_CLI_CONTRACT_REASON
    assert result["meta"]["selection_reason"] == LEGACY_CLI_CONTRACT_REASON


def test_detect_with_meta_error_invalid_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_rectifier_paths(tmp_path, monkeypatch)

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"points":"invalid","meta":{}}', stderr="")

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    with pytest.raises(RuntimeError, match="Unexpected detect payload type|points"):
        client.detect_with_meta(Path(r"D:\images\sample.jpg"))


def test_detect_with_meta_retries_without_with_meta_when_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_rectifier_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RECTIFIER_DETECT_ENGINE", "not-supported")

    captured_commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured_commands.append(command)
        if "--with-meta" in command:
            return SimpleNamespace(returncode=2, stdout="", stderr="unrecognized arguments: --with-meta")
        return SimpleNamespace(
            returncode=0,
            stdout='[{"x":1,"y":1},{"x":9,"y":1},{"x":9,"y":9},{"x":1,"y":9}]',
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)

    client = RectifierClient()
    result = client.detect_with_meta(Path(r"D:\images\sample.jpg"))

    assert len(captured_commands) == 2
    assert "--with-meta" in captured_commands[0]
    assert "--with-meta" not in captured_commands[1]
    engine_index = captured_commands[1].index("--engine") + 1
    assert captured_commands[1][engine_index] == "opencv"
    assert result["meta"]["fallback_reason"] == LEGACY_CLI_CONTRACT_REASON


def test_detect_returns_points_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_rectifier_paths(tmp_path, monkeypatch)

    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='[{"x":1,"y":1},{"x":9,"y":1},{"x":9,"y":9},{"x":1,"y":9}]',
            stderr="",
        )

    monkeypatch.setattr(rectifier_client_module.subprocess, "run", fake_run)
    client = RectifierClient()
    points = client.detect(Path(r"D:\images\sample.jpg"))
    assert points == [(1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0)]
