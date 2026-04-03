import json
from pathlib import Path

import pytest

from app.shared.io.json_store import read_json, write_json_atomic


def test_read_json_right_returns_payload(tmp_path: Path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({"a": 1, "b": "x"}), encoding="utf-8")

    assert read_json(path, default={}) == {"a": 1, "b": "x"}


def test_read_json_error_returns_default_on_corrupted_json(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{invalid-json", encoding="utf-8")
    default = {"fallback": True}

    assert read_json(path, default=default) == default


def test_write_json_atomic_conformance_replaces_target_file(tmp_path: Path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"old": True}), encoding="utf-8")

    write_json_atomic(target, {"new": 123, "ok": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": 123, "ok": True}
    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []


def test_write_json_atomic_error_cleans_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "target.json"

    def _raise_on_replace(self: Path, target_path: Path):  # noqa: ARG001
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", _raise_on_replace)

    with pytest.raises(OSError):
        write_json_atomic(target, {"x": 1})

    assert list(tmp_path.glob(f".{target.name}.*.tmp")) == []
