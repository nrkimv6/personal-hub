"""
PG 아카이브 테이블 생성 + 데이터 이동 스크립트

Phase 1: 파티셔닝 아카이브 테이블 DDL 생성
Phase 2: PG cold 데이터 이동 (monitoring_events, proxy_usage_logs, process_watch_snapshots)
Phase 3: SQLite instagram_posts → PG hot/archive 분배 이관

사용법:
    python scripts/create_archive_tables.py [--phase N] [--dry-run]

    --phase 1  : DDL만 실행
    --phase 2  : PG 내부 cold 데이터 이동
    --phase 3  : SQLite instagram_posts 이관
    --dry-run  : SQL 출력만, 실행 안 함
    (인자 없으면 전체 실행)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.core.database import engine


# ── Phase 1: DDL ──────────────────────────────────────────────

ARCHIVE_DDL = """
-- instagram_posts_archive (파티셔닝 부모)
CREATE TABLE IF NOT EXISTS instagram_posts_archive (
    id SERIAL,
    post_id VARCHAR NOT NULL,
    account VARCHAR NOT NULL,
    url VARCHAR,
    caption TEXT,
    images JSON,
    posted_at TIMESTAMP,
    display_time VARCHAR,
    is_ad BOOLEAN,
    post_type VARCHAR,
    likes INTEGER,
    comments INTEGER,
    is_reel BOOLEAN,
    duration DOUBLE PRECISION,
    music_title TEXT,
    music_artist TEXT,
    service_account_id INTEGER,
    crawl_run_id INTEGER,
    collected_at TIMESTAMP,
    source VARCHAR(20),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    last_seen_run_id INTEGER,
    is_active BOOLEAN,
    classified_type VARCHAR,
    classified_id INTEGER,
    classified_at TIMESTAMP,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- monitoring_events_archive (파티셔닝 부모)
CREATE TABLE IF NOT EXISTS monitoring_events_archive (
    id SERIAL,
    schedule_id INTEGER,
    status TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type VARCHAR,
    available_count INTEGER DEFAULT 0,
    slots_info TEXT,
    error_message TEXT,
    response_time_ms DOUBLE PRECISION,
    data_hash VARCHAR,
    hash_changed BOOLEAN DEFAULT false,
    fetch_method VARCHAR,
    time_range VARCHAR,
    original_slot_count INTEGER,
    filtered_slot_count INTEGER,
    target_time_matched BOOLEAN DEFAULT false,
    booking_triggered BOOLEAN DEFAULT false,
    booking_success BOOLEAN,
    proxy_url VARCHAR,
    graphql_response TEXT,
    graphql_time_ms DOUBLE PRECISION,
    proxy_retry_count INTEGER,
    booking_time_ms DOUBLE PRECISION,
    booking_attempt_count INTEGER,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- proxy_usage_logs_archive (파티셔닝 부모)
CREATE TABLE IF NOT EXISTS proxy_usage_logs_archive (
    id SERIAL,
    proxy_host TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_id TEXT,
    attempt_number INTEGER,
    schedule_id INTEGER,
    monitoring_event_id INTEGER,
    proxy_url TEXT,
    success INTEGER DEFAULT 0,
    http_status INTEGER,
    error_type TEXT,
    error_message TEXT,
    response_time_ms INTEGER,
    target_url TEXT,
    fetch_method TEXT,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- process_watch_snapshots_archive (파티셔닝 부모)
-- captured_at이 TEXT이므로 TEXT RANGE 파티셔닝 (ISO 8601 정렬 호환)
CREATE TABLE IF NOT EXISTS process_watch_snapshots_archive (
    id SERIAL,
    captured_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    ppid INTEGER,
    parent_pid INTEGER,
    parent_name TEXT,
    name TEXT,
    exe TEXT,
    cmdline TEXT,
    cmdline_hash TEXT,
    create_time DOUBLE PRECISION,
    memory_mb DOUBLE PRECISION,
    is_orphan INTEGER,
    scope TEXT,
    captured_by TEXT,
    PRIMARY KEY (id, captured_at)
) PARTITION BY RANGE (captured_at);
"""

# 월별 파티션 DDL
PARTITION_DDL = """
-- instagram_posts_archive 파티션 (SQLite 데이터 기간: 2025-12 ~ 2026-04)
CREATE TABLE IF NOT EXISTS instagram_posts_archive_y2025m12
    PARTITION OF instagram_posts_archive
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS instagram_posts_archive_y2026m01
    PARTITION OF instagram_posts_archive
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS instagram_posts_archive_y2026m02
    PARTITION OF instagram_posts_archive
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS instagram_posts_archive_y2026m03
    PARTITION OF instagram_posts_archive
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

-- monitoring_events_archive 파티션 (2025-12)
CREATE TABLE IF NOT EXISTS monitoring_events_archive_y2025m12
    PARTITION OF monitoring_events_archive
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

-- proxy_usage_logs_archive 파티션 (2025-12)
CREATE TABLE IF NOT EXISTS proxy_usage_logs_archive_y2025m12
    PARTITION OF proxy_usage_logs_archive
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

-- process_watch_snapshots_archive 파티션 (2026-04)
CREATE TABLE IF NOT EXISTS process_watch_snapshots_archive_y2026m04
    PARTITION OF process_watch_snapshots_archive
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- 인덱스 (파티션별 자동 상속)
CREATE INDEX IF NOT EXISTS idx_instagram_archive_account ON instagram_posts_archive (account);
CREATE INDEX IF NOT EXISTS idx_instagram_archive_posted_at ON instagram_posts_archive (posted_at);
CREATE INDEX IF NOT EXISTS idx_monitoring_events_archive_schedule ON monitoring_events_archive (schedule_id);
CREATE INDEX IF NOT EXISTS idx_proxy_archive_schedule ON proxy_usage_logs_archive (schedule_id);
CREATE INDEX IF NOT EXISTS idx_process_archive_pid ON process_watch_snapshots_archive (pid);
"""


def phase1_create_tables(dry_run=False):
    """Phase 1: 아카이브 테이블 + 파티션 DDL 생성"""
    print("\n=== Phase 1: 아카이브 테이블 DDL ===")

    if dry_run:
        print(ARCHIVE_DDL)
        print(PARTITION_DDL)
        return

    with engine.begin() as conn:
        for stmt in ARCHIVE_DDL.split(";"):
            # 주석 줄 제거 후 실질 SQL만 추출
            lines = [l for l in stmt.strip().splitlines() if not l.strip().startswith("--")]
            sql = "\n".join(lines).strip()
            if sql:
                conn.execute(text(sql))
        print("  ✅ 아카이브 부모 테이블 4개 생성 완료")

        for stmt in PARTITION_DDL.split(";"):
            lines = [l for l in stmt.strip().splitlines() if not l.strip().startswith("--")]
            sql = "\n".join(lines).strip()
            if sql:
                conn.execute(text(sql))
        print("  ✅ 월별 파티션 + 인덱스 생성 완료")

    # 검증
    insp = inspect(engine)
    tables = insp.get_table_names()
    archive_tables = [t for t in tables if "_archive" in t]
    print(f"  📋 생성된 아카이브 테이블: {len(archive_tables)}개")
    for t in sorted(archive_tables):
        print(f"     - {t}")


def phase2_move_pg_cold(dry_run=False):
    """Phase 2: PG 내부 cold 데이터 이동"""
    print("\n=== Phase 2: PG cold 데이터 이동 ===")

    moves = [
        {
            "name": "monitoring_events",
            "archive": "monitoring_events_archive",
            "date_col": "timestamp",
            "condition": "TRUE",  # 전체 이동 (종료된 모니터링)
        },
        {
            "name": "proxy_usage_logs",
            "archive": "proxy_usage_logs_archive",
            "date_col": "timestamp",
            "condition": "TRUE",  # 전체 이동
        },
        {
            "name": "process_watch_snapshots",
            "archive": "process_watch_snapshots_archive",
            "date_col": "captured_at",
            "condition": "captured_at < '2026-04-04'",  # 7일 이전
        },
    ]

    for m in moves:
        insert_sql = f"""
            INSERT INTO {m['archive']}
            SELECT * FROM {m['name']}
            WHERE {m['condition']}
        """
        delete_sql = f"""
            DELETE FROM {m['name']}
            WHERE {m['condition']}
        """

        if dry_run:
            print(f"\n-- {m['name']} → {m['archive']}")
            print(insert_sql)
            print(delete_sql)
            continue

        with engine.begin() as conn:
            # 이동 전 카운트
            before = conn.execute(
                text(f"SELECT COUNT(*) FROM {m['name']} WHERE {m['condition']}")
            ).scalar()
            print(f"\n  {m['name']}: {before}건 이동 대상")

            if before == 0:
                print(f"  ⏭️ 이동할 데이터 없음, 스킵")
                continue

            # INSERT INTO archive
            conn.execute(text(insert_sql))
            archived = conn.execute(
                text(f"SELECT COUNT(*) FROM {m['archive']}")
            ).scalar()
            print(f"  ✅ archive INSERT 완료: {archived}건")

            # DELETE from hot
            conn.execute(text(delete_sql))
            remaining = conn.execute(
                text(f"SELECT COUNT(*) FROM {m['name']}")
            ).scalar()
            print(f"  ✅ hot 테이블 정리 완료: {remaining}건 잔여")


def phase3_migrate_instagram(dry_run=False):
    """Phase 3: SQLite instagram_posts → PG hot/archive 분배"""
    print("\n=== Phase 3: SQLite instagram_posts → PG 이관 ===")

    import sqlite3
    from datetime import datetime, timedelta

    sqlite_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "monitor.db"
    )

    if not os.path.exists(sqlite_path):
        print(f"  ❌ SQLite 파일 없음: {sqlite_path}")
        return

    cutoff = datetime.now() - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  Hot/Cold 기준: {cutoff_str} (최근 30일)")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    # SQLite 컬럼 확인
    cursor.execute("PRAGMA table_info(instagram_posts)")
    sqlite_cols = [row[1] for row in cursor.fetchall()]
    print(f"  SQLite 컬럼: {len(sqlite_cols)}개")

    # PG 컬럼 확인 (id 제외 — SERIAL)
    insp = inspect(engine)
    pg_cols = [c["name"] for c in insp.get_columns("instagram_posts")]
    # 공통 컬럼 (id 제외)
    common_cols = [c for c in sqlite_cols if c in pg_cols and c != "id"]
    print(f"  공통 컬럼: {len(common_cols)}개 (id 제외)")

    # Hot 데이터 (최근 30일)
    cursor.execute(
        f"SELECT COUNT(*) FROM instagram_posts WHERE created_at >= ?",
        (cutoff_str,)
    )
    hot_count = cursor.fetchone()[0]

    # Cold 데이터 (30일 이전)
    cursor.execute(
        f"SELECT COUNT(*) FROM instagram_posts WHERE created_at < ? OR created_at IS NULL",
        (cutoff_str,)
    )
    cold_count = cursor.fetchone()[0]

    print(f"  Hot (최근 30일): {hot_count}건 → instagram_posts")
    print(f"  Cold (30일 이전): {cold_count}건 → instagram_posts_archive")

    if dry_run:
        print("  [dry-run] 실행 스킵")
        sqlite_conn.close()
        return

    col_list = ", ".join(common_cols)
    placeholders = ", ".join([f":{c}" for c in common_cols])

    # Hot 데이터 → instagram_posts
    if hot_count > 0:
        cursor.execute(
            f"SELECT {', '.join(common_cols)} FROM instagram_posts WHERE created_at >= ?",
            (cutoff_str,)
        )
        rows = [dict(row) for row in cursor.fetchall()]

        with engine.begin() as conn:
            # Boolean 변환
            bool_cols = {"is_ad", "is_reel", "is_active"}
            for row in rows:
                for bc in bool_cols:
                    if bc in row and row[bc] is not None:
                        row[bc] = bool(row[bc])

            insert_sql = text(
                f"INSERT INTO instagram_posts ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT (post_id) DO NOTHING"
            )
            conn.execute(insert_sql, rows)
        print(f"  ✅ Hot {len(rows)}건 → instagram_posts INSERT 완료")

    # Cold 데이터 → instagram_posts_archive
    if cold_count > 0:
        cursor.execute(
            f"SELECT {', '.join(common_cols)} FROM instagram_posts WHERE created_at < ? OR created_at IS NULL",
            (cutoff_str,)
        )
        rows = [dict(row) for row in cursor.fetchall()]

        # created_at NULL인 행은 가장 오래된 날짜로 채움
        null_created = sum(1 for r in rows if r.get("created_at") is None)
        if null_created > 0:
            print(f"  ⚠️ created_at NULL: {null_created}건 → 2025-12-01로 설정")
            for row in rows:
                if row.get("created_at") is None:
                    row["created_at"] = "2025-12-01 00:00:00"

        # Boolean 변환
        bool_cols = {"is_ad", "is_reel", "is_active"}
        for row in rows:
            for bc in bool_cols:
                if bc in row and row[bc] is not None:
                    row[bc] = bool(row[bc])

        with engine.begin() as conn:
            insert_sql = text(
                f"INSERT INTO instagram_posts_archive ({col_list}) VALUES ({placeholders})"
            )
            # 배치 INSERT (1000건씩)
            batch_size = 1000
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                conn.execute(insert_sql, batch)
                print(f"    ... {min(i + batch_size, len(rows))}/{len(rows)}")
        print(f"  ✅ Cold {len(rows)}건 → instagram_posts_archive INSERT 완료")

    sqlite_conn.close()

    # 검증
    with engine.connect() as conn:
        pg_hot = conn.execute(text("SELECT COUNT(*) FROM instagram_posts")).scalar()
        pg_cold = conn.execute(text("SELECT COUNT(*) FROM instagram_posts_archive")).scalar()
        print(f"\n  📋 최종 결과:")
        print(f"     instagram_posts (hot): {pg_hot}건")
        print(f"     instagram_posts_archive (cold): {pg_cold}건")


def main():
    parser = argparse.ArgumentParser(description="PG 아카이브 테이블 생성 + 데이터 이동")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], help="실행할 Phase (없으면 전체)")
    parser.add_argument("--dry-run", action="store_true", help="SQL 출력만, 실행 안 함")
    args = parser.parse_args()

    phases = [args.phase] if args.phase else [1, 2, 3]

    print("=" * 60)
    print("PG 아카이브 테이블 생성 + 데이터 이동")
    print(f"Phases: {phases}")
    if args.dry_run:
        print("⚠️ DRY RUN 모드 — SQL 출력만")
    print("=" * 60)

    if 1 in phases:
        phase1_create_tables(args.dry_run)
    if 2 in phases:
        phase2_move_pg_cold(args.dry_run)
    if 3 in phases:
        phase3_migrate_instagram(args.dry_run)

    print("\n" + "=" * 60)
    print("완료!")


if __name__ == "__main__":
    main()
