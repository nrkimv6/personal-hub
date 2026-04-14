"""
TC: PostgreSQL boolean 컬럼 타입 수정 마이그레이션 검증
마이그레이션 004_fix_boolean_column_types.py 실행 후 DB 상태를 검증한다.

관련 plan: docs/plan/2026-04-11_fix-boolean-column-type-pg-migration.md
"""
import sys
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.core.config import settings

# 변환 대상 (table, column) 20개 — child 파티션은 parent ALTER로 자동 전파됨
MIGRATED_COLUMNS = [
    ("accounts", "is_active"),
    ("accounts", "is_logged_in"),
    ("biz_items", "auto_booking_enabled"),
    ("businesses", "is_enabled"),
    ("entity_sources", "is_primary"),
    ("git_repos", "is_active"),
    ("instagram_post_tags", "is_active"),
    ("instagram_tag_keywords", "is_active"),
    ("instagram_tag_keywords", "is_case_sensitive"),
    ("instagram_tag_keywords", "is_regex"),
    ("keyword_stats", "is_promoted"),
    ("keyword_stats", "is_stopword"),
    ("monitor_schedules", "is_active"),
    ("monitor_schedules", "is_enabled"),
    ("notes", "is_pinned"),
    ("notes", "is_starred"),
    ("process_snapshots", "is_orphan"),
    ("process_watch_snapshots", "is_orphan"),
    ("process_watch_snapshots_archive", "is_orphan"),
    ("writing_elements", "is_active"),
]

# 파티션 child — parent ALTER로 자동 전파 검증
PARTITION_CHILDREN = [
    ("process_watch_snapshots_archive_y2026m04", "is_orphan"),
    ("process_watch_snapshots_archive_y2026m05", "is_orphan"),
]

# DEFAULT가 있는 컬럼 기대값
EXPECTED_DEFAULTS = {
    ("accounts", "is_active"): "true",
    ("accounts", "is_logged_in"): "false",
    ("biz_items", "auto_booking_enabled"): "false",
    ("businesses", "is_enabled"): "true",
    ("git_repos", "is_active"): "true",
    ("instagram_post_tags", "is_active"): "true",
    ("instagram_tag_keywords", "is_active"): "true",
    ("instagram_tag_keywords", "is_case_sensitive"): "false",
    ("instagram_tag_keywords", "is_regex"): "false",
    ("monitor_schedules", "is_active"): "false",
    ("monitor_schedules", "is_enabled"): "true",
}


@pytest.fixture(scope="module")
def pg_conn():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    yield cur
    conn.close()


# ============================================================
# R: 기본 동작 검증 — DB 타입 확인
# ============================================================

def test_boolean_columns_db_type_R(pg_conn):
    """R: 20개 컬럼 data_type이 모두 'boolean'인지 전수 확인"""
    placeholders = ",".join([f"('{t}', '{c}')" for t, c in MIGRATED_COLUMNS])
    pg_conn.execute(f"""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (table_name, column_name) IN ({placeholders})
        ORDER BY table_name, column_name
    """)
    rows = pg_conn.fetchall()

    violations = [(t, c, dt) for t, c, dt in rows if dt != "boolean"]
    assert not violations, (
        f"DB 타입이 boolean이 아닌 컬럼 발견: {violations}\n"
        f"마이그레이션 004_fix_boolean_column_types.py 재실행 필요"
    )
    assert len(rows) == len(MIGRATED_COLUMNS), (
        f"컬럼 수 불일치: 기대 {len(MIGRATED_COLUMNS)}개, 실제 {len(rows)}개"
    )


def test_boolean_columns_accept_false_literal_R(pg_conn):
    """R: monitor_schedules.is_enabled = false 쿼리가 에러 없이 실행되는지 확인"""
    pg_conn.execute("SELECT COUNT(*) FROM monitor_schedules WHERE is_enabled = false")
    result = pg_conn.fetchone()
    assert result is not None
    assert isinstance(result[0], int)


def test_boolean_columns_accept_true_literal_R(pg_conn):
    """R: monitor_schedules.is_enabled = true 쿼리가 에러 없이 실행되는지 확인"""
    pg_conn.execute("SELECT COUNT(*) FROM monitor_schedules WHERE is_enabled = true")
    result = pg_conn.fetchone()
    assert result is not None
    assert isinstance(result[0], int)


def test_partition_child_is_orphan_boolean_R(pg_conn):
    """R: 파티션 child 테이블 2개의 is_orphan이 boolean 타입인지 확인 (parent ALTER 자동 전파)"""
    for table, column in PARTITION_CHILDREN:
        pg_conn.execute(f"""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table}' AND column_name = '{column}'
        """)
        row = pg_conn.fetchone()
        assert row is not None, f"{table}.{column} 컬럼이 information_schema에 없음"
        assert row[0] == "boolean", (
            f"{table}.{column} 타입이 '{row[0]}'임 (기대: 'boolean') — "
            f"파티션 parent ALTER 자동 전파 실패"
        )


def test_defaults_correct_after_migration_R(pg_conn):
    """R: DEFAULT 값이 boolean으로 올바르게 설정되었는지 확인"""
    violations = []
    for (table, column), expected in EXPECTED_DEFAULTS.items():
        pg_conn.execute(f"""
            SELECT column_default FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table}' AND column_name = '{column}'
        """)
        row = pg_conn.fetchone()
        actual = row[0] if row else None
        if actual != expected:
            violations.append((table, column, expected, actual))

    assert not violations, (
        f"DEFAULT 값 불일치 발견 (기대, 실제): {violations}"
    )


# ============================================================
# E: 에러 재현 — integer 컬럼에 boolean 리터럴 사용 시 에러
# ============================================================

def test_integer_col_boolean_literal_raises_E(pg_conn):
    """E: integer 타입 컬럼에 boolean 리터럴 사용 시 UndefinedFunction 에러 재현"""
    try:
        pg_conn.execute(
            "ALTER TABLE monitor_schedules ADD COLUMN _test_int_col integer DEFAULT 0"
        )
        with pytest.raises(psycopg2.errors.UndefinedFunction):
            pg_conn.execute(
                "SELECT id FROM monitor_schedules WHERE _test_int_col = false"
            )
    finally:
        # 트랜잭션이 abort 상태일 수 있으므로 ROLLBACK 후 DROP
        pg_conn.connection.rollback()
        pg_conn.connection.autocommit = True
        pg_conn.execute(
            "ALTER TABLE monitor_schedules DROP COLUMN IF EXISTS _test_int_col"
        )


# ============================================================
# T3: 워커 실제 쿼리 경로 통합 TC
# ============================================================

def test_repro_worker_check_disabled_schedules_R(pg_conn):
    """T3/R: 실제 워커 경로 쿼리 — is_enabled = false 에러 없이 실행"""
    pg_conn.execute(
        "SELECT id FROM monitor_schedules WHERE is_enabled = false"
    )
    result = pg_conn.fetchall()
    assert isinstance(result, list)


def test_repro_integrity_check_query_R(pg_conn):
    """T3/R: 실제 워커 경로 쿼리 — is_enabled = true AND next_run_time IS NOT NULL 에러 없이 실행"""
    pg_conn.execute(
        "SELECT id FROM monitor_schedules WHERE is_enabled = true AND next_run_time IS NOT NULL"
    )
    result = pg_conn.fetchall()
    assert isinstance(result, list)
