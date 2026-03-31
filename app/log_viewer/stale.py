"""
stale.py — 로그 파일 stale 판정 로직

logs.ps1의 stale 판정 로직을 Python으로 이식한다.

판정 순서:
  1. 파일명에서 날짜(YYYY-MM-DD) 추출 → 오늘 날짜와 비교
  2. 날짜 없는 파일명 → reference_path의 LastWriteTime 기준 1시간 초과 시 stale
  3. reference_path 없으면 → stale로 처리
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

STALE_THRESHOLD_HOURS = 1  # 날짜 없는 파일의 stale 기준 (시간)


def _extract_date(filename: str) -> date | None:
    """파일명에서 YYYY-MM-DD 날짜를 추출한다. 없으면 None."""
    m = _DATE_PATTERN.search(filename)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_stale(
    file_path: Path,
    reference_path: Path | None = None,
    today: date | None = None,
) -> bool:
    """
    로그 파일이 stale(오래된/미사용)인지 판정한다.

    Parameters
    ----------
    file_path:       판정 대상 파일 경로
    reference_path:  날짜 없는 파일명의 경우 LastWriteTime 비교 기준 파일
                     (보통 최신 로그 파일). None이면 stale로 처리.
    today:           테스트용 날짜 주입. None이면 date.today() 사용.

    Returns
    -------
    bool — stale이면 True
    """
    if today is None:
        today = date.today()

    file_date = _extract_date(file_path.name)

    # 1차 판정: 파일명 날짜 기반
    if file_date is not None:
        return file_date < today

    # 2차 판정: 날짜 없는 파일명 → reference LastWriteTime 기준
    if reference_path is None:
        return True

    try:
        ref_mtime = datetime.fromtimestamp(reference_path.stat().st_mtime)
        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
    except OSError:
        return True

    # file의 LastWriteTime이 reference보다 STALE_THRESHOLD_HOURS 이상 오래됐으면 stale
    return (ref_mtime - file_mtime) > timedelta(hours=STALE_THRESHOLD_HOURS)
