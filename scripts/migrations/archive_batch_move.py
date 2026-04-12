"""
hot→archive 월별 배치 이동 스크립트

사용법:
    python scripts/archive_batch_move.py [--dry-run] [--cutoff-days N]

    --dry-run     : SQL 출력만, DB 변경 없음
    --cutoff-days : 이 일수보다 오래된 데이터를 archive로 이동 (기본: 30)
    --table       : 특정 테이블만 실행 (monitoring_events / proxy_usage_logs /
                    process_watch_snapshots / instagram_posts)
                    (기본: 전체)
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine, is_pg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("archive_batch_move")


def ensure_next_month_partitions(conn, dry_run: bool = False) -> None:
    """4개 아카이브 테이블에 대해 다음 달 파티션이 없으면 생성한다."""
    now = datetime.now()
    # 다음 달
    if now.month == 12:
        next_year, next_month = now.year + 1, 1
    else:
        next_year, next_month = now.year, now.month + 1

    start = datetime(next_year, next_month, 1)
    if next_month == 12:
        end = datetime(next_year + 1, 1, 1)
    else:
        end = datetime(next_year, next_month + 1, 1)

    tables = [
        "instagram_posts_archive",
        "monitoring_events_archive",
        "proxy_usage_logs_archive",
        "process_watch_snapshots_archive",
    ]
    for table in tables:
        partition_name = f"{table}_y{next_year}m{next_month:02d}"
        sql = (
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{start.strftime('%Y-%m-%d')}') "
            f"TO ('{end.strftime('%Y-%m-%d')}')"
        )
        if dry_run:
            logger.info("[DRY-RUN] %s", sql)
        else:
            try:
                conn.execute(text(sql))
                logger.info("파티션 확인/생성: %s", partition_name)
            except Exception as e:
                logger.warning("파티션 생성 스킵 (%s): %s", partition_name, e)


def move_monitoring_events(conn, cutoff: datetime, dry_run: bool = False) -> int:
    """monitoring_events → monitoring_events_archive 이동."""
    insert_sql = text("""
        INSERT INTO monitoring_events_archive
        SELECT id, schedule_id, status, timestamp, event_type,
               available_count, slots_info, error_message, response_time_ms,
               data_hash, hash_changed, fetch_method, time_range,
               original_slot_count, filtered_slot_count, target_time_matched,
               booking_triggered, booking_success, proxy_url, graphql_response,
               graphql_time_ms, proxy_retry_count, booking_time_ms, booking_attempt_count
        FROM monitoring_events
        WHERE timestamp < :cutoff
        ON CONFLICT DO NOTHING
    """)
    delete_sql = text("""
        DELETE FROM monitoring_events WHERE timestamp < :cutoff
    """)
    if dry_run:
        count_result = conn.execute(
            text("SELECT COUNT(*) FROM monitoring_events WHERE timestamp < :cutoff"),
            {"cutoff": cutoff},
        )
        count = count_result.scalar()
        logger.info("[DRY-RUN] monitoring_events: %d건 이동 예정", count)
        return count

    conn.execute(insert_sql, {"cutoff": cutoff})
    result = conn.execute(delete_sql, {"cutoff": cutoff})
    count = result.rowcount
    logger.info("monitoring_events: %d건 archive 이동 완료", count)
    return count


def move_proxy_usage_logs(conn, cutoff: datetime, dry_run: bool = False) -> int:
    """proxy_usage_logs → proxy_usage_logs_archive 이동."""
    insert_sql = text("""
        INSERT INTO proxy_usage_logs_archive
        SELECT id, proxy_host, timestamp, request_id, attempt_number,
               schedule_id, monitoring_event_id, proxy_url, success,
               http_status, error_type, error_message, response_time_ms,
               target_url, fetch_method
        FROM proxy_usage_logs
        WHERE timestamp < :cutoff
        ON CONFLICT DO NOTHING
    """)
    delete_sql = text("DELETE FROM proxy_usage_logs WHERE timestamp < :cutoff")
    if dry_run:
        count_result = conn.execute(
            text("SELECT COUNT(*) FROM proxy_usage_logs WHERE timestamp < :cutoff"),
            {"cutoff": cutoff},
        )
        count = count_result.scalar()
        logger.info("[DRY-RUN] proxy_usage_logs: %d건 이동 예정", count)
        return count

    conn.execute(insert_sql, {"cutoff": cutoff})
    result = conn.execute(delete_sql, {"cutoff": cutoff})
    count = result.rowcount
    logger.info("proxy_usage_logs: %d건 archive 이동 완료", count)
    return count


def move_process_watch_snapshots(conn, cutoff: datetime, dry_run: bool = False) -> int:
    """process_watch_snapshots → process_watch_snapshots_archive 이동.

    captured_at이 TEXT(ISO8601) 타입이므로 문자열 비교 사용.
    """
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    insert_sql = text("""
        INSERT INTO process_watch_snapshots_archive
        SELECT id, captured_at, pid, ppid, parent_pid, parent_name,
               name, exe, cmdline, cmdline_hash, create_time,
               memory_mb, is_orphan, scope, captured_by
        FROM process_watch_snapshots
        WHERE captured_at < :cutoff_str
        ON CONFLICT DO NOTHING
    """)
    delete_sql = text("DELETE FROM process_watch_snapshots WHERE captured_at < :cutoff_str")
    if dry_run:
        count_result = conn.execute(
            text("SELECT COUNT(*) FROM process_watch_snapshots WHERE captured_at < :cutoff_str"),
            {"cutoff_str": cutoff_str},
        )
        count = count_result.scalar()
        logger.info("[DRY-RUN] process_watch_snapshots: %d건 이동 예정", count)
        return count

    conn.execute(insert_sql, {"cutoff_str": cutoff_str})
    result = conn.execute(delete_sql, {"cutoff_str": cutoff_str})
    count = result.rowcount
    logger.info("process_watch_snapshots: %d건 archive 이동 완료", count)
    return count


def move_instagram_posts(conn, cutoff: datetime, dry_run: bool = False) -> int:
    """instagram_posts → instagram_posts_archive 이동.

    FK 참조 행(events, uncategorized_posts, popups의 source_instagram_post_id) 제외.
    """
    insert_sql = text("""
        INSERT INTO instagram_posts_archive
        SELECT id, post_id, account, url, caption, images,
               posted_at, display_time, is_ad, post_type, likes, comments,
               is_reel, duration, music_title, music_artist,
               service_account_id, crawl_run_id, collected_at, source,
               created_at, updated_at, last_seen_at, last_seen_run_id,
               is_active, classified_type, classified_id, classified_at
        FROM instagram_posts
        WHERE created_at < :cutoff
          AND id NOT IN (
              SELECT source_instagram_post_id FROM events
               WHERE source_instagram_post_id IS NOT NULL
              UNION
              SELECT source_instagram_post_id FROM uncategorized_posts
               WHERE source_instagram_post_id IS NOT NULL
              UNION
              SELECT source_instagram_post_id FROM popups
               WHERE source_instagram_post_id IS NOT NULL
          )
        ON CONFLICT DO NOTHING
    """)
    delete_sql = text("""
        DELETE FROM instagram_posts
        WHERE created_at < :cutoff
          AND id NOT IN (
              SELECT source_instagram_post_id FROM events
               WHERE source_instagram_post_id IS NOT NULL
              UNION
              SELECT source_instagram_post_id FROM uncategorized_posts
               WHERE source_instagram_post_id IS NOT NULL
              UNION
              SELECT source_instagram_post_id FROM popups
               WHERE source_instagram_post_id IS NOT NULL
          )
    """)
    if dry_run:
        count_result = conn.execute(
            text("""
                SELECT COUNT(*) FROM instagram_posts
                WHERE created_at < :cutoff
                  AND id NOT IN (
                      SELECT source_instagram_post_id FROM events WHERE source_instagram_post_id IS NOT NULL
                      UNION
                      SELECT source_instagram_post_id FROM uncategorized_posts WHERE source_instagram_post_id IS NOT NULL
                      UNION
                      SELECT source_instagram_post_id FROM popups WHERE source_instagram_post_id IS NOT NULL
                  )
            """),
            {"cutoff": cutoff},
        )
        count = count_result.scalar()
        logger.info("[DRY-RUN] instagram_posts: %d건 이동 예정 (FK 참조 행 제외됨)", count)
        return count

    conn.execute(insert_sql, {"cutoff": cutoff})
    result = conn.execute(delete_sql, {"cutoff": cutoff})
    count = result.rowcount
    logger.info("instagram_posts: %d건 archive 이동 완료 (FK 참조 행 제외됨)", count)
    return count


def run_batch(
    cutoff_days: int = 30,
    dry_run: bool = False,
    table: Optional[str] = None,
) -> dict:
    """배치 이동 메인 함수. 결과 dict 반환."""
    if not is_pg:
        logger.warning("SQLite 환경에서는 archive batch 실행 불가")
        return {}

    cutoff = datetime.now() - timedelta(days=cutoff_days)
    cutoff_pws = datetime.now() - timedelta(days=7)  # process_watch_snapshots는 7일

    results = {}

    with engine.begin() as conn:
        # 다음 달 파티션 보장
        ensure_next_month_partitions(conn, dry_run=dry_run)

        try:
            if table is None or table == "monitoring_events":
                results["monitoring_events"] = move_monitoring_events(conn, cutoff, dry_run)

            if table is None or table == "proxy_usage_logs":
                results["proxy_usage_logs"] = move_proxy_usage_logs(conn, cutoff, dry_run)

            if table is None or table == "process_watch_snapshots":
                results["process_watch_snapshots"] = move_process_watch_snapshots(conn, cutoff_pws, dry_run)

            if table is None or table == "instagram_posts":
                results["instagram_posts"] = move_instagram_posts(conn, cutoff, dry_run)

        except Exception as e:
            logger.error("배치 이동 중 오류 — 트랜잭션 롤백: %s", e, exc_info=True)
            raise

    total = sum(results.values())
    logger.info("배치 완료: 총 %d건 이동%s", total, " (dry-run)" if dry_run else "")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="hot→archive 배치 이동")
    parser.add_argument("--dry-run", action="store_true", help="실행 없이 건수만 출력")
    parser.add_argument("--cutoff-days", type=int, default=30, help="이 일수보다 오래된 데이터 이동 (기본: 30)")
    parser.add_argument(
        "--table",
        choices=["monitoring_events", "proxy_usage_logs", "process_watch_snapshots", "instagram_posts"],
        default=None,
        help="특정 테이블만 실행",
    )
    args = parser.parse_args()

    results = run_batch(cutoff_days=args.cutoff_days, dry_run=args.dry_run, table=args.table)
    for t, n in results.items():
        print(f"  {t}: {n}건")
