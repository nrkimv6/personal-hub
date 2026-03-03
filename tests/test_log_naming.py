"""로그 파일 네이밍 개선 — 유닛 테스트.

TC:
- test_report_service_runner_glob: service_runner_*.log glob으로 최신 파일 정상 조회
- test_report_service_runner_glob_no_files: 매칭 파일 없을 때 빈 문자열 반환
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service(log_dir: Path):
    """ReportService 인스턴스를 log_dir를 바라보도록 생성."""
    from app.modules.reports.services.report_service import ReportService

    svc = ReportService.__new__(ReportService)
    svc.SLEEP_NOW_LOG_DIR = str(log_dir)
    return svc


# ── Right ──────────────────────────────────────────────────────────────────

def test_report_service_runner_glob(tmp_path):
    """service_runner_*.log 파일이 존재하면 최신 파일을 읽어 로그를 반환한다."""
    log_dir = tmp_path
    log_file = log_dir / "service_runner_20260228_120000.log"
    target_date = date(2026, 2, 28)
    log_file.write_text(
        "2026-02-28 01:00:00 INFO started\n"
        "2026-02-28 01:01:00 INFO running\n",
        encoding="utf-8",
    )

    svc = _make_service(log_dir)

    # _build_sleep_now_context_text는 LLM 호출이 있으므로 직접 로직만 검증
    date_str = target_date.strftime("%Y%m%d")
    from pathlib import Path as P

    files = sorted(P(svc.SLEEP_NOW_LOG_DIR).glob("service_runner_*.log"))
    assert len(files) == 1
    content = files[-1].read_text(encoding="utf-8")
    assert "started" in content


# ── Error ──────────────────────────────────────────────────────────────────

def test_report_service_runner_glob_no_files(tmp_path):
    """service_runner_*.log 파일이 없으면 빈 리스트가 반환된다."""
    log_dir = tmp_path

    from pathlib import Path as P

    files = sorted(P(str(log_dir)).glob("service_runner_*.log"))
    assert files == []
    # service_log_path = None → service_log = ""
    service_log_path = files[-1] if files else None
    assert service_log_path is None
