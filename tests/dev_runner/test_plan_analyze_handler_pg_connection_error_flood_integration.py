"""
test_plan_analyze_handler_pg_connection_error_flood_integration.py — T3 통합 TC

fix: plan_analyze_handler PG connection error guard 재현 TC

실물 logging handler를 사용해 PG traceback flood 억제 계약을 검증한다:
  - psycopg2.OperationalError / sqlalchemy.exc.OperationalError 발생 시 warning-only
  - save path + recurrence path 연속 호출 시 warning 누적, exc_info 0건 유지
  - 비DB 예외에서는 traceback(exc_info)이 보존됨
"""
import logging
import psycopg2
import sqlalchemy.exc
import pytest
from unittest.mock import MagicMock, patch

import app.modules.claude_worker.services.plan_analyze_handler as _module
from app.modules.claude_worker.services.plan_analyze_handler import (
    save_plan_archive_result,
    _get_scope_overlap_candidates,
    detect_recurrence,
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

class _ListHandler(logging.Handler):
    """캡처 전용 Handler — emit 시 records 리스트에 추가."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _attach_handler(module_logger: logging.Logger) -> _ListHandler:
    handler = _ListHandler()
    handler.setLevel(logging.DEBUG)
    module_logger.addHandler(handler)
    module_logger.setLevel(logging.DEBUG)
    return handler


def _detach_handler(module_logger: logging.Logger, handler: _ListHandler) -> None:
    module_logger.removeHandler(handler)


def _make_request(caller_id: str = "hash_abc123") -> MagicMock:
    req = MagicMock()
    req.caller_id = caller_id
    return req


def _make_db_commit_pg_error() -> MagicMock:
    """commit 호출 시 psycopg2.OperationalError 발생하는 mock db."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = MagicMock(
        file_path=None,
        raw_content="existing",
        llm_processed_at=None,
        updated_at=None,
        intent="fix",
        scope='["naver_booking"]',
        id=42,
    )
    db.commit.side_effect = psycopg2.OperationalError("could not connect to server")
    return db


def _make_db_query_pg_error() -> MagicMock:
    """query 호출 시 sqlalchemy.exc.OperationalError 발생하는 mock db (psycopg2 orig)."""
    db = MagicMock()
    orig = psycopg2.OperationalError("could not connect to server")
    db.query.side_effect = sqlalchemy.exc.OperationalError(
        "SELECT ...", {}, orig
    )
    return db


def _make_plan_record(filename_hash: str = "hash_abc123") -> MagicMock:
    record = MagicMock()
    record.filename_hash = filename_hash
    record.category = "fix"
    record.scope = '["naver_booking"]'
    record.plan_date = None
    record.intent = "guard PG errors"
    return record


# ─────────────────────────────────────────────────────────────
# T3-1: save_plan_archive_result PG 오류 — 실물 handler 캡처
# ─────────────────────────────────────────────────────────────

def test_save_plan_archive_result_pg_error_real_handler_no_traceback():
    """
    T3(B): save_plan_archive_result에서 psycopg2.OperationalError 발생 시
    실물 logging.Handler로 warning 1회, exc_info 0건을 검증한다.
    """
    handler = _attach_handler(_module.logger)
    try:
        db = _make_db_commit_pg_error()
        result = save_plan_archive_result(db, _make_request(), {"result": {}, "success": True})

        assert result is False
        pg_warnings = [r for r in handler.records
                       if r.levelno == logging.WARNING and "connection error" in r.getMessage()]
        assert len(pg_warnings) >= 1, "PG connection error warning 없음"
        error_with_tb = [r for r in handler.records if r.levelno == logging.ERROR and r.exc_info]
        assert len(error_with_tb) == 0, f"traceback 로그 {len(error_with_tb)}건 발생"
        db.rollback.assert_called()
    finally:
        _detach_handler(_module.logger, handler)


# ─────────────────────────────────────────────────────────────
# T3-2: _get_scope_overlap_candidates sqlalchemy OperationalError
# ─────────────────────────────────────────────────────────────

def test_get_scope_overlap_candidates_sa_operational_error_no_traceback():
    """
    T3(B): _get_scope_overlap_candidates에서 sqlalchemy.exc.OperationalError(orig=psycopg2)
    발생 시 warning-only, [] 반환, traceback 없음.
    """
    handler = _attach_handler(_module.logger)
    try:
        db = _make_db_query_pg_error()
        record = _make_plan_record()

        candidates = _get_scope_overlap_candidates(db, record)

        assert candidates == [], f"빈 리스트 대신 {candidates!r} 반환"
        pg_warnings = [r for r in handler.records
                       if r.levelno == logging.WARNING and "connection error" in r.getMessage()]
        assert len(pg_warnings) >= 1, "PG connection error warning 없음"
        error_with_tb = [r for r in handler.records if r.levelno == logging.ERROR and r.exc_info]
        assert len(error_with_tb) == 0, f"traceback 로그 {len(error_with_tb)}건 발생"
    finally:
        _detach_handler(_module.logger, handler)


# ─────────────────────────────────────────────────────────────
# T3-3: save + recurrence 연속 호출 — warning 누적, exc_info=0
# ─────────────────────────────────────────────────────────────

def test_save_and_recurrence_sequential_pg_error_warnings_accumulate_no_traceback():
    """
    T3(C): save_plan_archive_result + _get_scope_overlap_candidates 연속 호출 시
    warning은 경로별로 누적되지만 exc_info 레코드는 끝까지 0건이다.
    """
    handler = _attach_handler(_module.logger)
    try:
        db_save = _make_db_commit_pg_error()
        save_plan_archive_result(db_save, _make_request("hash_save"), {"result": {}, "success": True})

        db_query = _make_db_query_pg_error()
        _get_scope_overlap_candidates(db_query, _make_plan_record("hash_query"))

        pg_warnings = [r for r in handler.records
                       if r.levelno == logging.WARNING and "connection error" in r.getMessage()]
        assert len(pg_warnings) >= 2, (
            f"연속 호출에서 warning {len(pg_warnings)}건 (최소 2건 필요)"
        )
        error_with_tb = [r for r in handler.records if r.levelno == logging.ERROR and r.exc_info]
        assert len(error_with_tb) == 0, f"traceback 로그 {len(error_with_tb)}건 발생"
    finally:
        _detach_handler(_module.logger, handler)


# ─────────────────────────────────────────────────────────────
# T3-4: 비DB 오류에서는 traceback(exc_info) 유지
# ─────────────────────────────────────────────────────────────

def test_save_plan_archive_result_non_pg_error_traceback_preserved():
    """
    T3(R): ValueError(비DB) 발생 시 ERROR+exc_info가 남는다.
    guard가 PG 오류만 선택적으로 억제하는지 검증.
    """
    handler = _attach_handler(_module.logger)
    try:
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = MagicMock(
            file_path=None,
            raw_content="x",
            llm_processed_at=None,
            updated_at=None,
            intent="fix",
            scope='["scope"]',
            id=1,
        )
        db.commit.side_effect = ValueError("unexpected value error")

        result = save_plan_archive_result(db, _make_request(), {"result": {}, "success": True})

        assert result is False
        error_with_tb = [r for r in handler.records if r.levelno == logging.ERROR and r.exc_info]
        assert len(error_with_tb) >= 1, "비DB 오류에서 traceback(exc_info) 누락"
        pg_warnings = [r for r in handler.records
                       if r.levelno == logging.WARNING and "connection error" in r.getMessage()]
        assert len(pg_warnings) == 0, "비DB 오류에서 PG warning이 잘못 기록됨"
    finally:
        _detach_handler(_module.logger, handler)
