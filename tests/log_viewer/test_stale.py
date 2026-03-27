"""
test_stale.py — stale 판정 로직 테스트

RIGHT-BICEP + CORRECT 기준:
  - Right: 오늘 날짜 파일 → not stale
  - Boundary: 자정 경계 (어제 23:59 vs 오늘)
  - Inverse: 미래 날짜 파일 → not stale
  - Error: 날짜 없는 파일명 + reference 없음 → stale
  - Cross-check: reference LastWriteTime 기반 판정
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.log_viewer.stale import is_stale


TODAY = date(2026, 3, 27)
YESTERDAY = date(2026, 3, 26)
TOMORROW = date(2026, 3, 28)


def _make_file(tmp_path: Path, name: str, content: str = "log") -> Path:
    f = tmp_path / name
    f.write_text(content)
    return f


# ─── 1차 판정: 파일명 날짜 기반 ───────────────────────────────────────────────

class TestFilenameDate:
    def test_today_not_stale(self, tmp_path):
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f, today=TODAY) is False

    def test_yesterday_stale(self, tmp_path):
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f, today=TODAY) is True

    def test_two_days_ago_stale(self, tmp_path):
        f = _make_file(tmp_path, "worker_2026-03-25.log")
        assert is_stale(f, today=TODAY) is True

    def test_tomorrow_not_stale(self, tmp_path):
        """미래 날짜 파일 → not stale (날짜 >= today)"""
        f = _make_file(tmp_path, "api_2026-03-28.log")
        assert is_stale(f, today=TODAY) is False

    def test_date_in_middle_of_name(self, tmp_path):
        """파일명 중간에 날짜가 있어도 추출 가능"""
        f = _make_file(tmp_path, "stdout_api_2026-03-26_001.log")
        assert is_stale(f, today=TODAY) is True

    def test_boundary_today_exact(self, tmp_path):
        """경계: 오늘 날짜 정확히 일치 → not stale"""
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f, today=date(2026, 3, 27)) is False

    def test_boundary_one_day_before(self, tmp_path):
        """경계: 하루 전 → stale"""
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True


# ─── 2차 판정: 날짜 없는 파일명 + reference LastWriteTime ────────────────────

class TestNoDateFallback:
    def test_no_reference_is_stale(self, tmp_path):
        """날짜 없는 파일 + reference None → stale"""
        f = _make_file(tmp_path, "latest.log")
        assert is_stale(f, reference_path=None, today=TODAY) is True

    def test_recent_file_not_stale(self, tmp_path):
        """file이 reference와 30분 차이 → not stale (임계값 1시간)"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        # file mtime = now, ref mtime = now + 30분 (file보다 최신)
        now = time.time()
        import os
        os.utime(f, (now, now))
        os.utime(ref, (now + 1800, now + 1800))  # ref가 30분 더 최신

        assert is_stale(f, reference_path=ref, today=TODAY) is False

    def test_stale_file_over_threshold(self, tmp_path):
        """file이 reference보다 2시간 오래됨 → stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        import os
        os.utime(f, (now - 7200, now - 7200))  # 2시간 전
        os.utime(ref, (now, now))

        assert is_stale(f, reference_path=ref, today=TODAY) is True

    def test_exactly_one_hour_not_stale(self, tmp_path):
        """file이 reference보다 정확히 1시간 오래됨 → not stale (> 기준, = 는 해당 없음)"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        import os
        os.utime(f, (now - 3600, now - 3600))  # 정확히 1시간 전
        os.utime(ref, (now, now))

        # timedelta(hours=1) 초과가 기준 → 정확히 1시간은 stale 아님
        assert is_stale(f, reference_path=ref, today=TODAY) is False

    def test_just_over_one_hour_stale(self, tmp_path):
        """file이 reference보다 1시간 1초 오래됨 → stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        import os
        os.utime(f, (now - 3601, now - 3601))
        os.utime(ref, (now, now))

        assert is_stale(f, reference_path=ref, today=TODAY) is True

    def test_no_date_plain_name(self, tmp_path):
        """날짜 없는 순수 이름 파일 + reference None → stale"""
        f = _make_file(tmp_path, "worker.log")
        assert is_stale(f, today=TODAY) is True
