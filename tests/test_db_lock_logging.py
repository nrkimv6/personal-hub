"""
SQLite 쓰기 잠금 감지 로깅 테스트

app/core/database.py에 추가된 훅 함수들을 독립적으로 검증한다.
in-memory SQLite 엔진을 사용하므로 실제 DB 파일에 영향 없음.
"""
import logging
import re
import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

# 테스트 대상 함수 직접 import
from app.core.database import (
    _get_caller_info,
    _on_before_cursor_execute,
    _on_after_cursor_execute,
    _on_handle_error,
    _on_session_after_commit,
    logger,
)


# ── 픽스처 ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mem_engine():
    """in-memory SQLite 엔진 (테스트 전용)"""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)"))
        conn.commit()
    yield eng
    eng.dispose()


@pytest.fixture()
def mem_session(mem_engine):
    """in-memory DB 세션"""
    Session = sessionmaker(bind=mem_engine)
    sess = Session()
    yield sess
    sess.close()


# ── _get_caller_info() ────────────────────────────────────────────────────

def test_get_caller_info_format():
    """R: 반환값이 '파일명:숫자 함수명' 패턴이어야 한다."""
    result = _get_caller_info()
    # 이 테스트 파일 자체가 app/ 경로가 아닐 수 있으므로 unknown도 허용
    # 핵심은 반환값이 str이고, 패턴이 맞거나 "unknown"이어야 함
    assert isinstance(result, str)
    if result != "unknown":
        assert re.search(r".+:\d+ \w+", result), f"패턴 불일치: {result!r}"


def test_get_caller_info_excludes_database_frame():
    """R: 반환값에 'database.py' 또는 'sqlalchemy' 미포함이어야 한다."""
    result = _get_caller_info()
    assert "database.py" not in result
    assert "sqlalchemy" not in result


def test_get_caller_info_no_app_frame():
    """B: traceback에 app/ 프레임이 없으면 'unknown'을 반환한다."""
    import traceback as tb_mod

    fake_frames = tb_mod.StackSummary.from_list([
        ("/site-packages/sqlalchemy/orm/session.py", 10, "commit", ""),
        ("/site-packages/pytest/runner.py", 20, "run", ""),
    ])
    with patch("traceback.extract_stack", return_value=fake_frames):
        result = _get_caller_info()
    assert result == "unknown"


# ── 엔진 이벤트 훅 ────────────────────────────────────────────────────────

def test_slow_query_warning(mem_engine, caplog):
    """R: 1초 초과 쓰기 쿼리 시 [DB-SLOW] WARNING이 출력된다."""
    with caplog.at_level(logging.WARNING, logger="db.lock"):
        with mem_engine.connect() as conn:
            # start_time을 1.5초 전으로 직접 주입
            conn.info["query_start_time"] = time.monotonic() - 1.5
            _on_after_cursor_execute(
                conn, None,
                "INSERT INTO t VALUES (1, 'x')",
                None, None, False
            )

    assert any("[DB-SLOW]" in r.message for r in caplog.records)


def test_fast_query_no_warning(mem_engine, caplog):
    """B: 빠른 쓰기 쿼리에는 [DB-SLOW]가 출력되지 않는다."""
    with caplog.at_level(logging.WARNING, logger="db.lock"):
        with mem_engine.connect() as conn:
            conn.info["query_start_time"] = time.monotonic() - 0.001
            _on_after_cursor_execute(
                conn, None,
                "INSERT INTO t VALUES (2, 'y')",
                None, None, False
            )
    assert not any("[DB-SLOW]" in r.message for r in caplog.records)


def test_select_query_not_tracked(mem_engine, caplog):
    """I: SELECT 쿼리는 before 훅에서 query_start_time을 저장하지 않는다."""
    with mem_engine.connect() as conn:
        conn.info.pop("query_start_time", None)
        _on_before_cursor_execute(conn, None, "SELECT * FROM t", None, None, False)
        assert "query_start_time" not in conn.info


def test_locked_error_logging(caplog):
    """E: 'database is locked' OperationalError 시 [DB-LOCKED] ERROR가 출력된다."""
    from sqlalchemy.exc import OperationalError

    exc_ctx = MagicMock()
    exc_ctx.original_exception = OperationalError("database is locked", None, None)
    exc_ctx.statement = "INSERT INTO t VALUES (3, 'z')"

    with caplog.at_level(logging.ERROR, logger="db.lock"):
        _on_handle_error(exc_ctx)

    assert any("[DB-LOCKED]" in r.message for r in caplog.records)


def test_locked_error_reports_operational_issue():
    """R: database locked 예외는 운영 장애 저장소로도 전달된다."""
    from sqlalchemy.exc import OperationalError

    exc_ctx = MagicMock()
    exc_ctx.original_exception = OperationalError("database is locked", None, None)
    exc_ctx.sqlalchemy_exception = OperationalError("stmt", {}, exc_ctx.original_exception)
    exc_ctx.statement = "INSERT INTO t VALUES (3, 'z')"
    exc_ctx.parameters = {"id": 3}
    exc_ctx.is_disconnect = False

    with patch("app.services.operational_issue_store.OperationalIssueReporter.report") as mock_report:
        _on_handle_error(exc_ctx)

    mock_report.assert_called_once()


# ── 세션 이벤트 훅 ────────────────────────────────────────────────────────

def test_slow_txn_commit_warning(caplog):
    """R: txn_start가 2.5초 전이면 [DB-SLOW-TXN] WARNING이 출력된다."""
    session = MagicMock()
    session.info = {"txn_start": time.monotonic() - 2.5}

    with caplog.at_level(logging.WARNING, logger="db.lock"):
        _on_session_after_commit(session)

    assert any("[DB-SLOW-TXN]" in r.message for r in caplog.records)


def test_fast_txn_no_warning(caplog):
    """B: txn_start가 0.5초 전이면 [DB-SLOW-TXN]이 출력되지 않는다."""
    session = MagicMock()
    session.info = {"txn_start": time.monotonic() - 0.5}

    with caplog.at_level(logging.WARNING, logger="db.lock"):
        _on_session_after_commit(session)

    assert not any("[DB-SLOW-TXN]" in r.message for r in caplog.records)


def test_txn_commit_without_begin(caplog):
    """E: session.info에 txn_start 키가 없어도 예외 없이 정상 완료된다."""
    session = MagicMock()
    session.info = {}

    with caplog.at_level(logging.WARNING, logger="db.lock"):
        _on_session_after_commit(session)  # 예외 없이 통과해야 함

    assert not any("[DB-SLOW-TXN]" in r.message for r in caplog.records)
