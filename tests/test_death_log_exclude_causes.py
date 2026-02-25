"""death_log.read_recent_deaths() exclude_causes 파라미터 테스트."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_entry(event: str, cause: str | None, minutes_ago: float = 1.0) -> dict:
    ts = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    return {
        "timestamp": ts,
        "pid": 12345,
        "event": event,
        "cause": cause,
        "exit_code": None,
        "uptime_seconds": 10,
        "details": None,
        "last_request": None,
    }


def _write_log(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 테스트 ─────────────────────────────────────────────────────────────

class TestReadRecentDeathsExcludeCauses:
    """read_recent_deaths(exclude_causes=...) 동작 검증."""

    def _run(self, entries: list[dict], **kwargs) -> list[dict]:
        """임시 log 파일을 만들고 read_recent_deaths()를 실행한다."""
        from app.core import death_log as dl

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs" / "death_log.json"
            _write_log(log_path, entries)
            with patch.object(dl, "_LOG_PATH", log_path):
                return dl.read_recent_deaths(**kwargs)

    # ── 기본 동작 (하위 호환) ──────────────────────────────────────

    def test_default_returns_all_deaths(self):
        """exclude_causes=None(기본값)이면 모든 death 이벤트를 반환한다."""
        entries = [
            _make_entry("death", "normal_shutdown"),
            _make_entry("death", "python_exception"),
            _make_entry("start", None),
        ]
        result = self._run(entries, window_minutes=5)
        assert len(result) == 2  # start 제외

    def test_default_includes_normal_shutdown(self):
        """기본값에서는 normal_shutdown도 포함된다."""
        entries = [_make_entry("death", "normal_shutdown")]
        result = self._run(entries, window_minutes=5)
        assert len(result) == 1
        assert result[0]["cause"] == "normal_shutdown"

    # ── exclude_causes 동작 ────────────────────────────────────────

    def test_excludes_normal_shutdown(self):
        """exclude_causes=['normal_shutdown']이면 normal_shutdown이 제외된다."""
        entries = [
            _make_entry("death", "normal_shutdown"),
            _make_entry("death", "python_exception"),
        ]
        result = self._run(entries, window_minutes=5, exclude_causes=["normal_shutdown"])
        assert len(result) == 1
        assert result[0]["cause"] == "python_exception"

    def test_excludes_multiple_causes(self):
        """여러 cause를 동시에 제외할 수 있다."""
        entries = [
            _make_entry("death", "normal_shutdown"),
            _make_entry("death", "signal"),
            _make_entry("death", "python_exception"),
        ]
        result = self._run(entries, window_minutes=5, exclude_causes=["normal_shutdown", "signal"])
        assert len(result) == 1
        assert result[0]["cause"] == "python_exception"

    def test_exclude_causes_empty_list_behaves_like_none(self):
        """exclude_causes=[]이면 아무것도 제외하지 않는다."""
        entries = [
            _make_entry("death", "normal_shutdown"),
            _make_entry("death", "python_exception"),
        ]
        result = self._run(entries, window_minutes=5, exclude_causes=[])
        assert len(result) == 2

    def test_returns_empty_when_all_excluded(self):
        """모든 death 이벤트가 제외되면 빈 리스트를 반환한다."""
        entries = [
            _make_entry("death", "normal_shutdown"),
            _make_entry("death", "normal_shutdown"),
        ]
        result = self._run(entries, window_minutes=5, exclude_causes=["normal_shutdown"])
        assert result == []

    # ── 시간 윈도우 적용 ──────────────────────────────────────────

    def test_window_still_applies_with_exclude_causes(self):
        """exclude_causes와 window_minutes 조건이 함께 적용된다."""
        entries = [
            _make_entry("death", "python_exception", minutes_ago=2.0),   # 윈도우 내
            _make_entry("death", "python_exception", minutes_ago=10.0),  # 윈도우 밖
        ]
        result = self._run(entries, window_minutes=5, exclude_causes=["normal_shutdown"])
        assert len(result) == 1

    # ── 빈 파일 / 파일 없음 ───────────────────────────────────────

    def test_no_log_file_returns_empty(self):
        """로그 파일이 없으면 빈 리스트를 반환한다."""
        from app.core import death_log as dl

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "logs" / "death_log.json"
            with patch.object(dl, "_LOG_PATH", missing_path):
                result = dl.read_recent_deaths(window_minutes=5, exclude_causes=["normal_shutdown"])
        assert result == []
