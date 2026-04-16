"""
PG boolean = integer 호환성 재현/통합 TC
SQLite→PostgreSQL 마이그레이션 후 boolean 컬럼에 integer 리터럴(0/1) 사용 시 에러 재현.

수정 후: true/false 리터럴 → 정상 동작.
"""
import re
import inspect
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

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

    def test_snapshot_writer_no_integer_boolean_literals(self):
        """재현 TC: snapshot_writer.py에 integer boolean 리터럴이 남아 있지 않은지 확인"""
        from app.shared.process import snapshot_writer

        source = inspect.getsource(snapshot_writer)
        assert "1 if bool(value) else 0" not in source
        assert "is_orphan = 1" not in source


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
        ("process_snapshots", "is_orphan"),
        ("process_watch_snapshots", "is_orphan"),
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
        assert "BOOLEAN DEFAULT FALSE" in source, "PG용 boolean default 없음"
        # AUTOINCREMENT는 f-string 내 SQLite 분기로 여전히 존재해야 함
        assert "AUTOINCREMENT" in source, "SQLite 분기 AUTOINCREMENT 없음"


class _FakeProc:
    def __init__(self, info):
        self.info = info


@pytest.fixture
def pg_session_factory():
    from app.core.config import settings

    schema = f"test_pws_bool_{uuid.uuid4().hex[:10]}"
    admin_conn = psycopg2.connect(settings.DATABASE_URL)
    admin_conn.autocommit = True
    admin_cur = admin_conn.cursor()
    admin_cur.execute(f'CREATE SCHEMA "{schema}"')

    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"options": f"-c search_path={schema}"},
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        yield session_factory, engine
    finally:
        engine.dispose()
        admin_cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_cur.close()
        admin_conn.close()


class TestSnapshotWriterPgRuntimeCompat:
    """실제 PostgreSQL 연결에서 SnapshotWriter boolean 바인딩 호환성을 검증한다."""

    @pytest.mark.asyncio
    async def test_capture_python_processes_inserts_pg_boolean(self, pg_session_factory):
        from app.shared.process.snapshot_writer import SnapshotWriter

        session_factory, engine = pg_session_factory
        registry = MagicMock()

        mem = MagicMock()
        mem.rss = 256 * 1024 * 1024
        proc = _FakeProc(
            {
                "pid": 81234,
                "name": "python.exe",
                "exe": r"D:\Python39\python.exe",
                "ppid": 5000,
                "cmdline": ["python", "-m", "pytest"],
                "memory_info": mem,
                "create_time": 1712100000.0,
            }
        )
        parent_proc = MagicMock()
        parent_proc.name.return_value = "cmd.exe"
        parent_proc.ppid.return_value = 1000

        with patch("app.shared.process.snapshot_writer.SessionLocal", session_factory), \
             patch("app.shared.process.snapshot_writer.is_pg", True), \
             patch("app.shared.process.snapshot_writer.psutil.process_iter", return_value=[proc]), \
             patch("app.shared.process.snapshot_writer.psutil.Process", return_value=parent_proc), \
             patch("app.shared.process.snapshot_writer.psutil.pid_exists", return_value=False), \
             patch.object(SnapshotWriter, "_purge_watch_rows", return_value=None):
            writer = SnapshotWriter(registry)
            count = await writer.capture_python_processes(limit=10, captured_by="test")

        assert count == 1
        with engine.begin() as conn:
            row = conn.execute(
                sa_text(
                    """
                    SELECT pid, is_orphan, scope, captured_by
                    FROM process_watch_snapshots
                    """
                )
            ).mappings().one()
        assert row["pid"] == 81234
        assert row["is_orphan"] is True
        assert row["scope"] == "external"
        assert row["captured_by"] == "test"
