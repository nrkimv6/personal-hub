"""tests/test_db_circuit_breaker.py

DbCircuitBreaker 단위 테스트 (Phase T1 - 항목 7)

테스트 명명 규칙: test_{동작}_{right|cross|boundary}
right  = 기본 동작 검증
cross  = 경계 조건 / 예외 경로
boundary = 임계치 경계
"""
import threading
import time
import unittest.mock as mock

import pytest
import sqlalchemy.exc


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db_circuit():
    """각 테스트 전 db_circuit 싱글턴 상태 초기화."""
    from app.core.database import db_circuit, _CLOSED
    with db_circuit._lock:
        db_circuit._state = _CLOSED
        db_circuit._fail_count = 0
        db_circuit._last_fail_time = 0.0
    yield
    # 테스트 후에도 리셋 (다음 테스트 격리)
    with db_circuit._lock:
        db_circuit._state = _CLOSED
        db_circuit._fail_count = 0
        db_circuit._last_fail_time = 0.0


# ── DbCircuitBreaker 상태 전이 ────────────────────────────────────────────────

def test_circuit_closed_allows_access_right():
    """초기 상태(CLOSED)에서 is_available() True."""
    from app.core.database import db_circuit
    assert db_circuit.is_available() is True
    assert db_circuit.get_status()["state"] == "closed"


def test_circuit_opens_after_threshold_boundary():
    """3회 record_failure() 후 OPEN 전이, is_available() False."""
    from app.core.database import db_circuit, _CB_THRESHOLD
    err = Exception("connection refused")
    for _ in range(_CB_THRESHOLD):
        db_circuit.record_failure(err)
    assert db_circuit.is_available() is False
    assert db_circuit.get_status()["state"] == "open"
    assert db_circuit.get_status()["fail_count"] == _CB_THRESHOLD


def test_circuit_not_open_before_threshold_boundary():
    """임계치 미도달(2회)에서는 OPEN 전이 없음."""
    from app.core.database import db_circuit, _CB_THRESHOLD
    err = Exception("connection refused")
    for _ in range(_CB_THRESHOLD - 1):
        db_circuit.record_failure(err)
    assert db_circuit.is_available() is True
    assert db_circuit.get_status()["state"] == "closed"


def test_circuit_half_open_after_cooldown_right():
    """OPEN 후 쿨다운 경과 시 is_available() True, 상태 HALF_OPEN."""
    from app.core.database import db_circuit, _CB_THRESHOLD
    err = Exception("connection refused")
    for _ in range(_CB_THRESHOLD):
        db_circuit.record_failure(err)

    # 쿨다운 경과를 모노토닉 시간으로 시뮬레이션
    with db_circuit._lock:
        db_circuit._last_fail_time = time.monotonic() - 11.0  # 10초 초과

    assert db_circuit.is_available() is True
    assert db_circuit.get_status()["state"] == "half_open"


def test_circuit_closes_on_success_right():
    """HALF_OPEN에서 record_success() 호출 시 CLOSED 전이, fail_count 0."""
    from app.core.database import db_circuit, _HALF_OPEN
    with db_circuit._lock:
        db_circuit._state = _HALF_OPEN
        db_circuit._fail_count = 3

    db_circuit.record_success()
    assert db_circuit.get_status()["state"] == "closed"
    assert db_circuit.get_status()["fail_count"] == 0


def test_circuit_reopens_on_half_open_failure_right():
    """HALF_OPEN에서 record_failure() 시 다시 OPEN 전이."""
    from app.core.database import db_circuit, _HALF_OPEN, _CB_THRESHOLD
    with db_circuit._lock:
        db_circuit._state = _HALF_OPEN
        db_circuit._fail_count = _CB_THRESHOLD  # 이미 임계치 도달 상태

    db_circuit.record_failure(Exception("timeout"))
    assert db_circuit.get_status()["state"] == "open"


def test_circuit_thread_safety_cross():
    """4개 스레드에서 동시 record_failure() 10회씩 호출해 상태 일관성 확인."""
    from app.core.database import db_circuit
    err = Exception("connection refused")
    errors_in_threads = []

    def worker():
        try:
            for _ in range(10):
                db_circuit.record_failure(err)
        except Exception as e:
            errors_in_threads.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors_in_threads, f"스레드 에러 발생: {errors_in_threads}"
    status = db_circuit.get_status()
    # 최소 임계치(3) 이상이면 OPEN이어야 함
    assert status["state"] == "open"
    assert status["fail_count"] == 40


# ── is_connection_error ───────────────────────────────────────────────────────

def test_is_connection_error_detects_pg_refused_right():
    """psycopg2.OperationalError('connection refused') 감지."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    from app.core.database import is_connection_error

    orig = psycopg2.OperationalError("connection refused\n")
    wrapped = sqlalchemy.exc.OperationalError("stmt", {}, orig)

    assert is_connection_error(orig) is True
    assert is_connection_error(wrapped) is True


def test_is_connection_error_detects_timeout_right():
    """psycopg2.OperationalError('timeout expired') 감지."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    from app.core.database import is_connection_error
    orig = psycopg2.OperationalError("timeout expired")
    assert is_connection_error(orig) is True


def test_is_connection_error_ignores_sqlite_locked_right():
    """SQLite OperationalError('database is locked') — False 반환."""
    from app.core.database import is_connection_error
    exc = Exception("database is locked")  # SQLite 에러 (psycopg2 아님)
    assert is_connection_error(exc) is False


def test_is_connection_error_ignores_generic_error_right():
    """일반 ValueError는 False 반환."""
    from app.core.database import is_connection_error
    assert is_connection_error(ValueError("something wrong")) is False


def test_is_connection_error_detects_sqlstate_08_right():
    """pgcode '08006'을 가진 psycopg2.OperationalError 감지 (string fallback)."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    from app.core.database import is_connection_error
    # pgcode가 없어도 메시지 기반으로 감지
    orig = psycopg2.OperationalError("server closed the connection unexpectedly")
    assert is_connection_error(orig) is True


def test_is_connection_error_without_pgcode_falls_back_to_message_right():
    """pgcode 없는 경우 메시지 'could not connect'로 fallback 감지."""
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 없음")

    from app.core.database import is_connection_error
    orig = psycopg2.OperationalError("could not connect to server")
    assert is_connection_error(orig) is True
