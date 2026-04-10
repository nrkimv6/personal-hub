"""
PG boolean = integer 호환성 재현/통합 TC
SQLite→PostgreSQL 마이그레이션 후 boolean 컬럼에 integer 리터럴(0/1) 사용 시 에러 재현.

수정 후: true/false 리터럴 → 정상 동작.
"""
import re
import inspect
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ============================================================
# 1. 수정된 코드에서 PG 호환 리터럴 사용 확인 (소스코드 레벨)
# ============================================================

class TestPgBooleanCompatSourceCheck:
    """수정된 소스코드에 integer 리터럴(0/1)이 boolean 컬럼에 사용되지 않는지 검증"""

    BAD_PATTERN = re.compile(
        r'(?:is_enabled|is_disabled|is_active)\s*=\s*[01]\b'
    )

    def _get_raw_sql_from_source(self, source: str) -> list[str]:
        """text(...) 내부 SQL 문자열 추출 (단순 패턴)"""
        # text(""" ... """) 블록 추출
        blocks = re.findall(r'text\s*\(\s*(?:f?""")(.*?)(?:""")\s*\)', source, re.DOTALL)
        # text("...") 단일 따옴표 블록 추출
        blocks += re.findall(r'text\s*\(\s*(?:f?")(.*?)(?:")\s*\)', source, re.DOTALL)
        return blocks

    def test_naver_monitor_worker_no_integer_boolean(self):
        """재현 TC: naver_monitor_worker.py raw SQL에서 boolean=integer 제거 확인"""
        from app.worker import naver_monitor_worker
        source = inspect.getsource(naver_monitor_worker)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, (
            f"boolean = integer 패턴 발견 (PG에서 UndefinedFunction 에러 발생): {violations}"
        )

    def test_dashboard_routes_no_integer_boolean(self):
        """재현 TC: dashboard.py raw SQL에서 boolean=integer 제거 확인"""
        from app.routes import dashboard
        source = inspect.getsource(dashboard)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, f"dashboard.py boolean=integer 패턴: {violations}"

    def test_system_routes_no_integer_boolean(self):
        """재현 TC: system.py raw SQL에서 boolean=integer 제거 확인"""
        from app.routes import system
        source = inspect.getsource(system)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, f"system.py boolean=integer 패턴: {violations}"

    def test_worker_routes_no_integer_boolean(self):
        """재현 TC: worker.py raw SQL에서 boolean=integer 제거 확인"""
        from app.routes import worker
        source = inspect.getsource(worker)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, f"worker.py boolean=integer 패턴: {violations}"

    def test_integrity_check_service_no_integer_boolean(self):
        """재현 TC: integrity_check_service.py에서 boolean=integer 제거 확인"""
        from app.services import integrity_check_service
        source = inspect.getsource(integrity_check_service)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, f"integrity_check_service.py boolean=integer 패턴: {violations}"

    def test_schedule_service_no_integer_boolean(self):
        """재현 TC: schedule_service.py에서 boolean=integer 제거 확인"""
        from app.modules.naver_booking.services import schedule_service
        source = inspect.getsource(schedule_service)
        sql_blocks = self._get_raw_sql_from_source(source)
        violations = []
        for block in sql_blocks:
            matches = self.BAD_PATTERN.findall(block)
            if matches:
                violations.extend(matches)
        assert not violations, f"schedule_service.py boolean=integer 패턴: {violations}"


class TestLastInsertRowidRemoved:
    """last_insert_rowid() → RETURNING id 교체 확인"""

    def test_service_account_no_last_insert_rowid(self):
        """재현 TC: service_account.py에서 last_insert_rowid() 제거 확인"""
        from app.routes import service_account
        source = inspect.getsource(service_account)
        assert "last_insert_rowid" not in source, (
            "service_account.py에 last_insert_rowid() 남아있음 — PG에서 함수 없음 에러"
        )
        assert "RETURNING id" in source, "RETURNING id 패턴이 없음"

    def test_instagram_routes_no_last_insert_rowid(self):
        """재현 TC: instagram.py에서 last_insert_rowid() 제거 확인"""
        from app.modules.instagram.routes import instagram
        source = inspect.getsource(instagram)
        assert "last_insert_rowid" not in source, (
            "instagram.py에 last_insert_rowid() 남아있음"
        )
        assert "RETURNING id" in source, "RETURNING id 패턴이 없음"


@pytest.fixture(scope="module")
def pg_conn():
    from app.core.config import settings
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    yield cur
    conn.close()


class TestPgBooleanDbTypeCheck:
    """DB 실제 컬럼 타입 검증 — 마이그레이션 004 이후 boolean 타입 보장"""

    BOOLEAN_COLUMNS = [
        ("accounts", "is_active"),
        ("accounts", "is_logged_in"),
        ("biz_items", "auto_booking_enabled"),
        ("businesses", "is_enabled"),
        ("monitor_schedules", "is_active"),
        ("monitor_schedules", "is_enabled"),
        ("instagram_tag_keywords", "is_active"),
        ("instagram_tag_keywords", "is_case_sensitive"),
        ("instagram_tag_keywords", "is_regex"),
        ("process_watch_snapshots_archive", "is_orphan"),
    ]

    def test_db_column_types_are_boolean(self, pg_conn):
        """DB 타입 전수 검증 — integer 컬럼이 boolean 리터럴 쿼리에서 에러를 유발하는 재발 방지"""
        placeholders = ",".join([f"('{t}', '{c}')" for t, c in self.BOOLEAN_COLUMNS])
        pg_conn.execute(f"""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (table_name, column_name) IN ({placeholders})
        """)
        rows = pg_conn.fetchall()
        violations = [(t, c, dt) for t, c, dt in rows if dt != "boolean"]
        assert not violations, (
            f"DB 타입이 integer인 boolean 컬럼 발견: {violations}\n"
            f"마이그레이션 004_fix_boolean_column_types.py 재실행 필요"
        )


class TestSnapshotWriterPgDdl:
    """snapshot_writer AUTOINCREMENT → SERIAL 분기 확인"""

    def test_ensure_watch_tables_has_pg_branch(self):
        """재현 TC: _ensure_watch_tables에 is_pg 분기 존재 확인"""
        from app.shared.process import snapshot_writer
        source = inspect.getsource(snapshot_writer.SnapshotWriter._ensure_watch_tables)
        assert "is_pg" in source, "_ensure_watch_tables에 is_pg 분기 없음"
        assert "SERIAL PRIMARY KEY" in source, "PG용 SERIAL 없음"
        # AUTOINCREMENT는 f-string 내 SQLite 분기로 여전히 존재해야 함
        assert "AUTOINCREMENT" in source, "SQLite 분기 AUTOINCREMENT 없음"
