"""death_log._trim_log() 유닛테스트."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _write_lines(path: Path, n: int) -> None:
    path.write_text("\n".join(f'{{"line": {i}}}' for i in range(n)) + "\n", encoding="utf-8")


def _line_count(path: Path) -> int:
    return len([l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()])


# ── Right ──────────────────────────────────────────────────────────────────

def test_trim_log_over_limit(tmp_path):
    """501줄 → 트리밍 후 500줄만 남아야 한다."""
    log = tmp_path / "death_log.json"
    _write_lines(log, 501)

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log(keep=500)

    assert _line_count(log) == 500


def test_trim_log_keeps_latest_lines(tmp_path):
    """트리밍 후 최신(뒤쪽) 줄이 보존돼야 한다."""
    log = tmp_path / "death_log.json"
    lines = [f'{{"seq": {i}}}' for i in range(600)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log(keep=500)

    remaining = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    import json
    assert json.loads(remaining[0])["seq"] == 100   # 앞 100줄 제거됨
    assert json.loads(remaining[-1])["seq"] == 599  # 마지막 줄 보존


# ── Boundary ───────────────────────────────────────────────────────────────

def test_trim_log_exactly_at_limit(tmp_path):
    """정확히 500줄이면 no-op이어야 한다."""
    log = tmp_path / "death_log.json"
    _write_lines(log, 500)
    original = log.read_text(encoding="utf-8")

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log(keep=500)

    assert log.read_text(encoding="utf-8") == original


def test_trim_log_under_limit(tmp_path):
    """499줄이면 no-op이어야 한다."""
    log = tmp_path / "death_log.json"
    _write_lines(log, 499)
    original = log.read_text(encoding="utf-8")

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log(keep=500)

    assert log.read_text(encoding="utf-8") == original


# ── Error / Edge ───────────────────────────────────────────────────────────

def test_trim_log_file_absent(tmp_path):
    """파일이 없어도 예외 없이 no-op이어야 한다."""
    log = tmp_path / "nonexistent.json"

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log()  # should not raise


def test_trim_log_empty_file(tmp_path):
    """빈 파일이어도 예외 없이 no-op이어야 한다."""
    log = tmp_path / "death_log.json"
    log.write_text("", encoding="utf-8")

    with patch("app.core.death_log._LOG_PATH", log):
        from app.core.death_log import _trim_log
        _trim_log()

    assert log.read_text(encoding="utf-8") == ""


# ── record_start 연동 ───────────────────────────────────────────────────────

def test_record_start_triggers_trim(tmp_path):
    """record_start() 호출 시 501줄이면 트리밍이 실행돼야 한다."""
    log = tmp_path / "death_log.json"
    _write_lines(log, 501)

    with patch("app.core.death_log._LOG_PATH", log):
        import importlib
        import app.core.death_log as dl
        importlib.reload(dl)
        dl._LOG_PATH = log
        dl.record_start()

    assert _line_count(log) <= 501  # 트리밍 후 start 엔트리 1줄 추가되므로 ≤ 501
