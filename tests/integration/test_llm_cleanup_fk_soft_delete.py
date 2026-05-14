"""Integration checks for cleanup history with child llm_request references."""

from datetime import datetime, timedelta
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.bootstrap import load_all_models
from app.models.writing import GeneratedWriting
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.reports.models.generated_report import GeneratedReport

pytestmark = pytest.mark.integration

try:
    import psycopg2
    from psycopg2 import sql

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL = PROJECT_ROOT / "app" / "migrations" / "2026-05-14_llm_request_fk_set_null.sql"


@pytest.fixture
def db_session():
    load_all_models()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _request_with_children(db_session):
    old_time = datetime.now() - timedelta(days=8)
    request = LLMRequest(
        caller_type="test_cleanup_fk",
        caller_id="with-children",
        prompt="cleanup fk",
        status="completed",
        requested_at=old_time - timedelta(hours=1),
        processed_at=old_time,
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)

    writing = GeneratedWriting(
        task_type=GeneratedWriting.TASK_TYPE_MIX,
        content="generated content",
        llm_request_id=request.id,
    )
    report = GeneratedReport(
        report_type="cleanup_test",
        period_start=old_time - timedelta(days=1),
        period_end=old_time,
        content="report content",
        llm_request_id=request.id,
    )
    db_session.add_all([writing, report])
    db_session.commit()
    return request, writing.id, report.id


def test_cleanup_old_history_R_default_soft_delete_preserves_child_fk(db_session):
    request, writing_id, report_id = _request_with_children(db_session)
    service = LLMService(db_session)

    count = service.cleanup_old_history(days=7)

    assert count == 1
    db_session.refresh(request)
    assert request.deleted_at is not None
    assert db_session.get(GeneratedWriting, writing_id).llm_request_id == request.id
    assert db_session.get(GeneratedReport, report_id).llm_request_id == request.id


def test_cleanup_old_history_R_hard_delete_sets_child_fk_null(db_session):
    request, writing_id, report_id = _request_with_children(db_session)
    request_id = request.id
    service = LLMService(db_session)

    count = service.cleanup_old_history(days=7, hard_delete=True)

    assert count == 1
    assert db_session.get(LLMRequest, request_id) is None
    db_session.expire_all()
    writing = db_session.get(GeneratedWriting, writing_id)
    report = db_session.get(GeneratedReport, report_id)
    assert writing.content == "generated content"
    assert report.content == "report content"
    assert writing.llm_request_id is None
    assert report.llm_request_id is None


def test_llm_request_fk_R_pg_migration_replaces_constraints_and_sets_null():
    """PG: old FK shape -> migration -> hard delete nulls child refs."""
    if not HAS_PSYCOPG2:
        pytest.skip("psycopg2가 없어 PG integration test를 실행할 수 없습니다.")

    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor",
    )
    schema_name = f"test_llm_fk_set_null_{uuid4().hex[:10]}"
    migration_sql = MIGRATION_SQL.read_text(encoding="utf-8")

    try:
        conn = psycopg2.connect(base_url)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PG integration DB 연결 불가: {exc}")

    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            cur.execute(
                """
                CREATE TABLE llm_requests (
                    id SERIAL PRIMARY KEY,
                    caller_type TEXT NOT NULL,
                    caller_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    processed_at TIMESTAMP,
                    deleted_at TIMESTAMP
                );
                CREATE TABLE generated_writings (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    llm_request_id INTEGER REFERENCES llm_requests(id)
                );
                CREATE TABLE generated_reports (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    llm_request_id INTEGER REFERENCES llm_requests(id)
                );
                """
            )
            cur.execute(migration_sql)
            cur.execute(
                """
                SELECT conname, confdeltype
                FROM pg_constraint
                WHERE conrelid::regclass::text IN ('generated_writings', 'generated_reports')
                  AND contype = 'f'
                ORDER BY conname
                """
            )
            constraints = dict(cur.fetchall())
            assert constraints == {
                "generated_reports_llm_request_id_fkey": "n",
                "generated_writings_llm_request_id_fkey": "n",
            }

            cur.execute(
                """
                INSERT INTO llm_requests (caller_type, caller_id, prompt, status, processed_at)
                VALUES ('test', 'pg', 'prompt', 'completed', NOW() - INTERVAL '8 days')
                RETURNING id
                """
            )
            request_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO generated_writings (content, llm_request_id) VALUES ('writing', %s) RETURNING id",
                (request_id,),
            )
            writing_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO generated_reports (content, llm_request_id) VALUES ('report', %s) RETURNING id",
                (request_id,),
            )
            report_id = cur.fetchone()[0]

            cur.execute("DELETE FROM llm_requests WHERE id = %s", (request_id,))
            cur.execute("SELECT content, llm_request_id FROM generated_writings WHERE id = %s", (writing_id,))
            assert cur.fetchone() == ("writing", None)
            cur.execute("SELECT content, llm_request_id FROM generated_reports WHERE id = %s", (report_id,))
            assert cur.fetchone() == ("report", None)
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
        finally:
            conn.close()
