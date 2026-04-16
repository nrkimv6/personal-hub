"""
Integrity PG 통합 테스트 (T3)

실제 PostgreSQL 연결에서 IntegrityCheckService가 SQLite 메타쿼리 없이
통계/검사를 수행하는지 검증한다.
"""
import logging

import pytest

from app.services.integrity_check_service import IntegrityCheckService


@pytest.fixture(scope="module")
def pg_db():
    from app.database import SessionLocal
    from app.core.database import is_pg

    if not is_pg:
        pytest.skip("PostgreSQL 전용 테스트")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.integration
def test_get_db_stats_pg_returns_numeric_counts(pg_db):
    """R: PG 환경에서 DB 통계가 전부 null로 무너지지 않아야 한다."""
    service = IntegrityCheckService(pg_db)

    stats = service.get_db_stats()

    assert "tables" in stats
    assert "db_size_bytes" in stats
    assert "db_size_mb" in stats
    assert stats["db_size_bytes"] >= 0
    assert any(isinstance(count, int) for count in stats["tables"].values()), (
        "PG 환경에서는 최소 한 개 이상의 테이블 카운트가 숫자로 복구되어야 함"
    )
    assert all(count is None or isinstance(count, int) for count in stats["tables"].values())


@pytest.mark.integration
def test_run_full_check_pg_returns_list_without_sqlite_metadata_error(pg_db, caplog):
    """R: PG 환경에서 정합성 검사 중 sqlite_master/PRAGMA 경고가 나오지 않아야 한다."""
    service = IntegrityCheckService(pg_db)

    with caplog.at_level(logging.WARNING, logger="app.services.integrity_check_service"):
        issues = service.run_full_check()

    assert isinstance(issues, list)
    sqlite_metadata_logs = [
        record.message
        for record in caplog.records
        if "sqlite_master" in record.message or "PRAGMA table_info" in record.message
    ]
    assert not sqlite_metadata_logs, (
        f"SQLite 메타쿼리 경고가 남아있음: {sqlite_metadata_logs}"
    )
