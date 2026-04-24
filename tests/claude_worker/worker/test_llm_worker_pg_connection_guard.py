"""LLMWorker PG 연결 오류 guard TC.

B: PG 연결 오류 시 warning 1회만 기록, exc_info=True traceback 없음
R: 비DB 오류(ValueError 등)는 exc_info=True 유지
"""
import logging
import pytest
import psycopg2
import sqlalchemy.exc
from unittest.mock import MagicMock

from app.modules.claude_worker.worker.worker import (
    save_instagram_result,
    save_writing_result,
)


def _make_instagram_db(flush_error=None, commit_error=None):
    """save_instagram_result용 DB mock."""
    db = MagicMock()
    post_mock = MagicMock()
    post_mock.images = []
    db.query.return_value.filter.return_value.first.return_value = post_mock
    if flush_error:
        db.flush.side_effect = flush_error
    if commit_error:
        db.commit.side_effect = commit_error
    return db


def _make_writing_db(commit_error=None):
    """save_writing_result용 DB mock. flush는 writing.id를 세팅하므로 성공하게 두고 commit에서 오류."""
    db = MagicMock()
    batch_mock = MagicMock()
    batch_mock.increment_completed = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = batch_mock
    if commit_error:
        db.commit.side_effect = commit_error
    return db


def _make_writing_request():
    req = MagicMock()
    req.id = 1
    req.caller_id = "1"
    req.writing_metadata = None
    req.writing_batch_id = None
    return req


# ──────────────────────────────────────────────────
# B: Boundary — PG 연결 오류 시 warning 1회, traceback 없음
# ──────────────────────────────────────────────────

def test_save_instagram_result_pg_connection_error_no_traceback(caplog):
    """B: psycopg2.OperationalError(connection) 시 warning 1회, exc_info traceback 없음."""
    db = _make_instagram_db(flush_error=psycopg2.OperationalError("could not connect to server"))

    with caplog.at_level(logging.DEBUG):
        result = save_instagram_result(db, post_id=1, llm_result={"tag": "이벤트"})

    assert result is False
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "PG connection error" in r.message]
    assert len(pg_warnings) == 1, f"Expected 1 PG warning, got {len(pg_warnings)}"
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0


def test_save_instagram_result_sqlalchemy_pg_error_no_traceback(caplog):
    """B: sqlalchemy.exc.OperationalError(orig=psycopg2) 시 warning 1회, exc_info 없음."""
    orig = psycopg2.OperationalError("could not connect to server")
    db = _make_instagram_db(flush_error=sqlalchemy.exc.OperationalError("stmt", {}, orig))

    with caplog.at_level(logging.DEBUG):
        result = save_instagram_result(db, post_id=1, llm_result={"tag": "이벤트"})

    assert result is False
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "PG connection error" in r.message]
    assert len(pg_warnings) == 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0


def test_save_writing_result_pg_connection_error_no_traceback(caplog):
    """B: save_writing_result에서 PG 연결 오류 시 warning 1회, traceback 없음."""
    db = _make_writing_db(commit_error=psycopg2.OperationalError("could not connect to server"))
    req = _make_writing_request()

    with caplog.at_level(logging.DEBUG):
        result = save_writing_result(db, req, {"task_type": "refine", "raw_response": "x"})

    assert result is False
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "PG connection error" in r.message]
    assert len(pg_warnings) == 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0


# ──────────────────────────────────────────────────
# R: Right — 비DB 오류는 exc_info=True 유지
# ──────────────────────────────────────────────────

def test_save_instagram_result_non_pg_error_preserves_exc_info(caplog):
    """R: ValueError 같은 비DB 오류는 exc_info=True로 traceback 기록."""
    db = _make_instagram_db(flush_error=ValueError("unexpected non-pg error"))

    with caplog.at_level(logging.DEBUG):
        result = save_instagram_result(db, post_id=1, llm_result={"tag": "이벤트"})

    assert result is False
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) >= 1
    pg_warnings = [r for r in caplog.records if "PG connection error" in r.message]
    assert len(pg_warnings) == 0


def test_save_writing_result_non_pg_error_preserves_exc_info(caplog):
    """R: save_writing_result에서 RuntimeError(비DB) 시 exc_info 유지."""
    db = _make_writing_db(commit_error=RuntimeError("unexpected runtime error"))
    req = _make_writing_request()

    with caplog.at_level(logging.DEBUG):
        result = save_writing_result(db, req, {"task_type": "refine", "raw_response": "x"})

    assert result is False
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) >= 1
    pg_warnings = [r for r in caplog.records if "PG connection error" in r.message]
    assert len(pg_warnings) == 0
