"""
test_stale.py — stale 판정 로직 테스트

RIGHT-BICEP + CORRECT 기준:
  - Right: 오늘 날짜 파일 → not stale
  - Boundary: 자정 경계 (어제 23:59 vs 오늘 00:00)
  - Inverse: 미래 날짜 파일 → not stale
  - Error: 날짜 없는 파일명 + reference 없음 → stale
  - Cross-check: reference LastWriteTime 기반 판정

freezegun으로 date.today()를 고정하여 today= 파라미터 없이 테스트한다.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time

from app.log_viewer.stale import _extract_date, is_stale


def _make_file(tmp_path: Path, name: str, content: str = "log") -> Path:
    f = tmp_path / name
    f.write_text(content)
    return f


# ─── 1차 판정: 파일명 날짜 기반 (today= 파라미터 직접 주입) ───────────────────

class TestFilenameDate:
    def test_today_not_stale(self, tmp_path):
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f, today=date(2026, 3, 27)) is False

    def test_yesterday_stale(self, tmp_path):
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True

    def test_two_days_ago_stale(self, tmp_path):
        f = _make_file(tmp_path, "worker_2026-03-25.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True

    def test_tomorrow_not_stale(self, tmp_path):
        """미래 날짜 파일 → not stale (날짜 >= today)"""
        f = _make_file(tmp_path, "api_2026-03-28.log")
        assert is_stale(f, today=date(2026, 3, 27)) is False

    def test_date_in_middle_of_name(self, tmp_path):
        """파일명 중간에 날짜가 있어도 추출 가능"""
        f = _make_file(tmp_path, "stdout_api_2026-03-26_001.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True

    def test_boundary_today_exact(self, tmp_path):
        """경계: 오늘 날짜 정확히 일치 → not stale"""
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f, today=date(2026, 3, 27)) is False

    def test_boundary_one_day_before(self, tmp_path):
        """경계: 하루 전 → stale"""
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True


# ─── freezegun: date.today() 고정 테스트 ────────────────────────────────────
#
# is_stale()에 today= 파라미터를 전달하지 않고,
# @freeze_time으로 date.today()를 고정하여 실제 운영 환경과 동일한 흐름을 검증한다.


class TestFreezetime:
    @freeze_time("2026-03-27")
    def test_today_file_not_stale(self, tmp_path):
        """freezegun: 오늘 날짜 파일 → not stale (today= 없이 호출)"""
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f) is False

    @freeze_time("2026-03-27")
    def test_yesterday_file_stale(self, tmp_path):
        """freezegun: 어제 날짜 파일 → stale"""
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f) is True

    @freeze_time("2026-03-27")
    def test_future_file_not_stale(self, tmp_path):
        """freezegun: 미래 날짜 파일 → not stale"""
        f = _make_file(tmp_path, "api_2026-03-28.log")
        assert is_stale(f) is False

    @freeze_time("2026-03-27 00:00:00")
    def test_boundary_midnight_today_not_stale(self, tmp_path):
        """자정 경계: 오늘 00:00:00 고정 시 오늘 날짜 파일 → not stale"""
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f) is False

    @freeze_time("2026-03-27 00:00:00")
    def test_boundary_midnight_yesterday_stale(self, tmp_path):
        """자정 경계: 오늘 00:00:00 고정 시 어제 날짜 파일 → stale"""
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f) is True

    @freeze_time("2026-03-27 23:59:59")
    def test_boundary_end_of_day_today_not_stale(self, tmp_path):
        """자정 경계: 오늘 23:59:59 고정 시 오늘 날짜 파일 → not stale"""
        f = _make_file(tmp_path, "api_2026-03-27.log")
        assert is_stale(f) is False

    @freeze_time("2026-03-27 23:59:59")
    def test_boundary_end_of_day_yesterday_stale(self, tmp_path):
        """자정 경계: 오늘 23:59:59 고정 시 어제 날짜 파일 → stale"""
        f = _make_file(tmp_path, "api_2026-03-26.log")
        assert is_stale(f) is True

    @freeze_time("2026-03-27")
    def test_no_date_no_reference_stale(self, tmp_path):
        """freezegun: 날짜 없는 파일명 + reference None → stale"""
        f = _make_file(tmp_path, "latest.log")
        assert is_stale(f) is True

    @freeze_time("2026-03-27")
    def test_no_date_recent_reference_not_stale(self, tmp_path):
        """freezegun: 날짜 없는 파일 + reference와 30분 차이 → not stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now, now))
        os.utime(ref, (now + 1800, now + 1800))  # ref가 30분 더 최신

        assert is_stale(f, reference_path=ref) is False

    @freeze_time("2026-03-27")
    def test_no_date_old_reference_stale(self, tmp_path):
        """freezegun: 날짜 없는 파일 + reference보다 2시간 오래됨 → stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now - 7200, now - 7200))  # 2시간 전
        os.utime(ref, (now, now))

        assert is_stale(f, reference_path=ref) is True


# ─── 2차 판정: 날짜 없는 파일명 + reference LastWriteTime ────────────────────

class TestNoDateFallback:
    def test_no_reference_is_stale(self, tmp_path):
        """날짜 없는 파일 + reference None → stale"""
        f = _make_file(tmp_path, "latest.log")
        assert is_stale(f, reference_path=None, today=date(2026, 3, 27)) is True

    def test_recent_file_not_stale(self, tmp_path):
        """file이 reference와 30분 차이 → not stale (임계값 1시간)"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now, now))
        os.utime(ref, (now + 1800, now + 1800))  # ref가 30분 더 최신

        assert is_stale(f, reference_path=ref, today=date(2026, 3, 27)) is False

    def test_stale_file_over_threshold(self, tmp_path):
        """file이 reference보다 2시간 오래됨 → stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now - 7200, now - 7200))  # 2시간 전
        os.utime(ref, (now, now))

        assert is_stale(f, reference_path=ref, today=date(2026, 3, 27)) is True

    def test_exactly_one_hour_not_stale(self, tmp_path):
        """file이 reference보다 정확히 1시간 오래됨 → not stale (> 기준, = 는 해당 없음)"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now - 3600, now - 3600))  # 정확히 1시간 전
        os.utime(ref, (now, now))

        # timedelta(hours=1) 초과가 기준 → 정확히 1시간은 stale 아님
        assert is_stale(f, reference_path=ref, today=date(2026, 3, 27)) is False

    def test_just_over_one_hour_stale(self, tmp_path):
        """file이 reference보다 1시간 1초 오래됨 → stale"""
        ref = _make_file(tmp_path, "ref.log")
        f = _make_file(tmp_path, "latest.log")

        now = time.time()
        os.utime(f, (now - 3601, now - 3601))
        os.utime(ref, (now, now))

        assert is_stale(f, reference_path=ref, today=date(2026, 3, 27)) is True

    def test_no_date_plain_name(self, tmp_path):
        """날짜 없는 순수 이름 파일 + reference None → stale"""
        f = _make_file(tmp_path, "worker.log")
        assert is_stale(f, today=date(2026, 3, 27)) is True


# ---------------------------------------------------------------------------
# _extract_date: 밑줄 형식 지원 TC (Phase T1 — Phase 22 대응)
# ---------------------------------------------------------------------------


class TestExtractDateUnderscore:
    def test_extract_date_underscore_format(self):
        """R: api_20260407_120000.log → date(2026, 4, 7) 반환."""
        result = _extract_date("api_20260407_120000.log")
        assert result == date(2026, 4, 7)

    def test_extract_date_hyphen_format_regression(self):
        """B: 기존 하이픈 형식 plan-runner-2026-04-07-abc.log → 회귀 없음."""
        result = _extract_date("plan-runner-2026-04-07-abc.log")
        assert result == date(2026, 4, 7)

    def test_extract_date_underscore_stale_yesterday(self, tmp_path):
        """R: 어제 밑줄형식 파일 → is_stale=True (stale 판정 정상 동작)."""
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        fname = f"api_{yesterday.strftime('%Y%m%d')}_120000.log"
        f = _make_file(tmp_path, fname)
        assert is_stale(f) is True

    def test_extract_date_underscore_today_not_stale(self, tmp_path):
        """R: 오늘 밑줄형식 파일 → is_stale=False."""
        fname = f"api_{date.today().strftime('%Y%m%d')}_120000.log"
        f = _make_file(tmp_path, fname)
        assert is_stale(f) is False

    def test_extract_date_no_match(self):
        """E: 날짜 패턴 없는 파일명 → None 반환."""
        assert _extract_date("worker.log") is None
        assert _extract_date("stdout_api.log") is None
