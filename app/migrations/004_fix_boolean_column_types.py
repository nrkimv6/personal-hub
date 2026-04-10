"""
PostgreSQL boolean 컬럼 타입 수정 마이그레이션
SQLite→PG 마이그레이션 시 integer로 변환된 boolean 컬럼을 실제 boolean으로 ALTER

배경:
  - 2026-03-07 SQLite→PG 마이그레이션 시 boolean 컬럼이 integer(0/1)로 변환됨
  - 2026-04-10 fix(806bca11)에서 raw SQL을 = 0/1 → = false/true로 변경했으나
    DB 컬럼이 여전히 integer여서 "operator does not exist: integer = boolean" 에러 발생
  - 이 스크립트는 22개 컬럼을 boolean 타입으로 ALTER하여 근본 해결

실행 방법:
    python app/migrations/004_fix_boolean_column_types.py

관련 plan:
    docs/plan/2026-04-11_fix-boolean-column-type-pg-migration.md
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from app.core.config import settings

# (table, column, default: bool | None)
# default=True  → ALTER COLUMN SET DEFAULT true
# default=False → ALTER COLUMN SET DEFAULT false
# default=None  → DEFAULT 변경 없음
COLUMNS_TO_FIX = [
    # accounts 테이블 — service_accounts.is_logged_in(boolean)과 다른 테이블
    ("accounts", "is_active", True),
    ("accounts", "is_logged_in", False),
    ("biz_items", "auto_booking_enabled", False),
    ("businesses", "is_enabled", True),
    ("entity_sources", "is_primary", None),
    ("git_repos", "is_active", True),
    ("instagram_post_tags", "is_active", True),
    ("instagram_tag_keywords", "is_active", True),
    ("instagram_tag_keywords", "is_case_sensitive", False),
    ("instagram_tag_keywords", "is_regex", False),
    ("keyword_stats", "is_promoted", None),
    ("keyword_stats", "is_stopword", None),
    ("monitor_schedules", "is_active", False),
    ("monitor_schedules", "is_enabled", True),
    ("notes", "is_pinned", None),
    ("notes", "is_starred", None),
    ("process_snapshots", "is_orphan", None),
    ("process_watch_snapshots", "is_orphan", None),
    # 파티션 parent — PostgreSQL에서 parent ALTER 시 inherited 컬럼은 child에 자동 전파됨
    # child 테이블(y2026m04, y2026m05)에서 직접 ALTER하면 "cannot alter inherited column" 에러 발생
    # → parent만 ALTER하면 child는 자동 반영
    ("process_watch_snapshots_archive", "is_orphan", None),
    ("writing_elements", "is_active", None),
]


def alter_column(cur, table: str, column: str, default_val) -> str | None:
    """컬럼 타입을 boolean으로 변환. 실패 시 에러 메시지 반환, 성공 시 None 반환"""
    try:
        # Step 1: 기존 DEFAULT DROP (integer DEFAULT가 boolean 캐스트를 막음)
        cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        # Step 2: 타입 변환 (0→false, 1→true)
        cur.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE boolean USING {column}::boolean"
        )
        # Step 3: boolean DEFAULT 복원
        if default_val is not None:
            default_str = "true" if default_val else "false"
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default_str}")
        return None
    except Exception as e:
        return str(e)


def run() -> None:
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"[004] PostgreSQL boolean 컬럼 타입 수정 마이그레이션 시작")
    print(f"[004] 대상 컬럼 수: {len(COLUMNS_TO_FIX)}개\n")

    errors = []
    for table, column, default_val in COLUMNS_TO_FIX:
        # 컬럼별 SAVEPOINT — 하나 실패해도 다른 컬럼은 계속 처리
        cur.execute("SAVEPOINT col_sp")
        err = alter_column(cur, table, column, default_val)
        if err:
            cur.execute("ROLLBACK TO SAVEPOINT col_sp")
            errors.append((table, column, err))
            print(f"  ERROR: {table}.{column} → {err}")
        else:
            cur.execute("RELEASE SAVEPOINT col_sp")
            suffix = f" (DEFAULT {'true' if default_val else 'false'})" if default_val is not None else ""
            print(f"  OK: {table}.{column}{suffix}")

    if errors:
        conn.rollback()
        print(f"\n[004] ROLLBACK — {len(errors)}개 컬럼 에러 발생:")
        for t, c, msg in errors:
            print(f"  - {t}.{c}: {msg}")
        conn.close()
        sys.exit(1)

    conn.commit()
    print(f"\n[004] COMMIT 완료\n")

    # 검증: information_schema에서 22개 컬럼 data_type 확인
    table_col_pairs = [(t, c) for t, c, _ in COLUMNS_TO_FIX]
    placeholders = ",".join([f"('{t}', '{c}')" for t, c in table_col_pairs])
    cur.execute(f"""
        SELECT table_name, column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (table_name, column_name) IN ({placeholders})
        ORDER BY table_name, column_name
    """)
    rows = cur.fetchall()

    print("[004] 검증 결과:")
    remaining_integer = []
    for row in rows:
        tbl, col, dtype, dflt = row
        status = "OK" if dtype == "boolean" else "WARN"
        if dtype != "boolean":
            remaining_integer.append((tbl, col, dtype))
        print(f"  {status}: {tbl}.{col} → {dtype} (default={dflt})")

    if remaining_integer:
        print(f"\n[004] WARN — 여전히 integer인 컬럼 {len(remaining_integer)}개:")
        for t, c, dt in remaining_integer:
            print(f"  - {t}.{c}: {dt}")
    else:
        print(f"\n[004] 전체 {len(rows)}개 컬럼 boolean 변환 확인 완료")

    conn.close()


if __name__ == "__main__":
    run()
