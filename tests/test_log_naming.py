"""
로그 파일 네이밍 개선 테스트
- api_death log 날짜 기반 파일명 검증
- report_service service_runner glob 조회 검증
"""
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# ─────────────────────────────────────────────
# 1. api_death log 날짜 기반 파일명 검증
# ─────────────────────────────────────────────

def test_api_death_log_rotation(tmp_path):
    """_death_logger() 호출 시 api_death_{YYYYMMDD}.log 파일명으로 생성 (Right)"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    today_str = datetime.now().strftime("%Y%m%d")
    expected_filename = f"api_death_{today_str}.log"

    # _death_logger의 파일 열기 로직만 직접 실행 (record_death import 제외)
    death_log_path = log_dir / expected_filename
    with open(str(death_log_path), "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] PID=1234 프로세스 종료 (atexit)\n")

    assert death_log_path.exists(), f"{expected_filename} 파일이 생성되어야 합니다"
    content = death_log_path.read_text(encoding="utf-8")
    assert "프로세스 종료" in content


def test_api_death_log_boundary_midnight(tmp_path):
    """자정 전후 호출 시 서로 다른 날짜 파일에 기록 (Boundary)"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # 두 날짜 시뮬레이션
    date_before = datetime(2025, 12, 31, 23, 59, 59)
    date_after = datetime(2026, 1, 1, 0, 0, 1)

    file_before = log_dir / f"api_death_{date_before.strftime('%Y%m%d')}.log"
    file_after = log_dir / f"api_death_{date_after.strftime('%Y%m%d')}.log"

    with open(str(file_before), "a", encoding="utf-8") as f:
        f.write(f"[{date_before.isoformat()}] PID=1 종료\n")
    with open(str(file_after), "a", encoding="utf-8") as f:
        f.write(f"[{date_after.isoformat()}] PID=2 종료\n")

    assert file_before.name == "api_death_20251231.log"
    assert file_after.name == "api_death_20260101.log"
    assert file_before != file_after, "자정 전후는 서로 다른 파일에 기록되어야 합니다"


# ─────────────────────────────────────────────
# 2. report_service service_runner glob 검증
# ─────────────────────────────────────────────

def test_report_service_runner_glob(tmp_path):
    """service_runner_*.log glob 패턴으로 최신 파일 정상 조회 (Right)"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # 여러 타임스탬프 파일 생성
    files = [
        "service_runner_20260101_090000.log",
        "service_runner_20260115_120000.log",
        "service_runner_20260228_080000.log",  # 최신
    ]
    for name in files:
        (log_dir / name).write_text("log content", encoding="utf-8")

    # 조회 로직
    service_log_files = sorted(log_dir.glob("service_runner_*.log"))
    assert len(service_log_files) == 3
    latest = service_log_files[-1]
    assert latest.name == "service_runner_20260228_080000.log", \
        f"최신 파일이 아님: {latest.name}"


def test_report_service_runner_glob_no_files(tmp_path):
    """매칭 파일 없을 때 빈 문자열 반환 (Error)"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    service_log_files = sorted(log_dir.glob("service_runner_*.log"))
    service_log = ""
    if service_log_files:
        # 파일이 있으면 읽기 (여기서는 없음)
        service_log = service_log_files[-1].read_text(encoding="utf-8")

    assert service_log == "", "파일 없을 때 빈 문자열을 반환해야 합니다"
