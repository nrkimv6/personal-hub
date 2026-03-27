"""
tests/log_viewer/conftest.py — 공통 fixture

로그 디렉토리 구조 생성과 파일 생성 헬퍼를 제공한다.
각 테스트 모듈에서 공통으로 사용할 fixture를 이 파일에 모은다.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# 로그 디렉토리 구조 fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def log_dirs(tmp_path: Path) -> dict[str, Path]:
    """
    표준 로그 디렉토리 구조를 생성한다.

    Returns:
        {
            "base":  <tmp_path>/logs/          # 공개용 로그
            "admin": <tmp_path>/logs/admin/    # admin 전용 로그
        }
    """
    base = tmp_path / "logs"
    admin = base / "admin"
    base.mkdir(parents=True, exist_ok=True)
    admin.mkdir(parents=True, exist_ok=True)
    return {"base": base, "admin": admin}


# ---------------------------------------------------------------------------
# 파일 생성 헬퍼 fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_log_file() -> Callable[..., Path]:
    """
    로그 파일 생성 헬퍼를 반환한다.

    Usage::

        def test_something(log_dirs, make_log_file):
            f = make_log_file(log_dirs["base"], "api_2026-03-27.log", content=b"line1\\n")
    """

    def _make(directory: Path, filename: str, content: bytes = b"log line\n") -> Path:
        """지정 디렉토리에 파일을 생성하고 Path를 반환한다."""
        path = directory / filename
        path.write_bytes(content)
        return path

    return _make


@pytest.fixture()
def make_empty_log_file() -> Callable[..., Path]:
    """
    빈 로그 파일 생성 헬퍼를 반환한다.

    Usage::

        def test_skip_empty(log_dirs, make_empty_log_file):
            empty = make_empty_log_file(log_dirs["base"], "api_2026-03-27.log")
    """

    def _make(directory: Path, filename: str) -> Path:
        """지정 디렉토리에 0바이트 파일을 생성하고 Path를 반환한다."""
        path = directory / filename
        path.write_bytes(b"")
        return path

    return _make


# ---------------------------------------------------------------------------
# 날짜 기반 파일명 생성 헬퍼
# ---------------------------------------------------------------------------


def log_filename(prefix: str, d: date, ext: str = ".log") -> str:
    """
    날짜가 포함된 로그 파일명을 반환한다.

    Examples::

        log_filename("api_", date(2026, 3, 27))   # "api_2026-03-27.log"
        log_filename("worker_", date(2026, 3, 26)) # "worker_2026-03-26.log"
    """
    return f"{prefix}{d.isoformat()}{ext}"


# ---------------------------------------------------------------------------
# 파일 mtime 조작 헬퍼
# ---------------------------------------------------------------------------


def set_file_mtime(path: Path, dt: datetime) -> None:
    """
    파일의 수정 시각(mtime)을 지정한 datetime으로 변경한다.
    stale 판정 테스트에서 LastWriteTime을 시뮬레이션할 때 사용한다.
    """
    ts = dt.timestamp()
    os.utime(path, (ts, ts))
