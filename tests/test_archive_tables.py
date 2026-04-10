"""PG 아카이브 테이블 파티셔닝 검증 TC"""

import pytest
from sqlalchemy import text, inspect
from app.core.database import engine


@pytest.fixture
def db_conn():
    with engine.connect() as conn:
        yield conn


class TestArchiveDDL:
    """Phase T1: 아카이브 테이블 존재 및 구조 검증"""

    def test_archive_tables_exist(self, db_conn):
        """R: 아카이브 부모 테이블 4개 존재 확인"""
        insp = inspect(engine)
        tables = insp.get_table_names()
        expected = [
            "instagram_posts_archive",
            "monitoring_events_archive",
            "proxy_usage_logs_archive",
            "process_watch_snapshots_archive",
        ]
        for t in expected:
            assert t in tables, f"아카이브 테이블 {t} 미존재"

    def test_archive_partitions_exist(self, db_conn):
        """R: 월별 파티션 존재 확인"""
        insp = inspect(engine)
        tables = insp.get_table_names()

        partitions = {
            "instagram_posts_archive_y2025m12",
            "instagram_posts_archive_y2026m01",
            "instagram_posts_archive_y2026m02",
            "instagram_posts_archive_y2026m03",
            "monitoring_events_archive_y2025m12",
            "proxy_usage_logs_archive_y2025m12",
            "process_watch_snapshots_archive_y2026m04",
        }
        for p in partitions:
            assert p in tables, f"파티션 {p} 미존재"

    def test_archive_insert_routed_to_correct_partition(self, db_conn):
        """B: 날짜별 올바른 파티션에 INSERT 되는지 확인"""
        with engine.begin() as conn:
            # 2025-12 파티션에 테스트 행 INSERT
            conn.execute(text("""
                INSERT INTO monitoring_events_archive (schedule_id, status, timestamp)
                VALUES (99999, 'test_routing', '2025-12-15 00:00:00')
            """))

            # 파티션에서 직접 조회
            result = conn.execute(text("""
                SELECT COUNT(*) FROM monitoring_events_archive_y2025m12
                WHERE schedule_id = 99999
            """)).scalar()
            assert result == 1, "2025-12 파티션 라우팅 실패"

            # 정리
            conn.execute(text("""
                DELETE FROM monitoring_events_archive WHERE schedule_id = 99999
            """))

    def test_hot_table_schema_unchanged(self, db_conn):
        """R: 기존 ORM 테이블 스키마 변경 없음"""
        insp = inspect(engine)

        # instagram_posts 원본 테이블 컬럼 확인
        cols = {c["name"] for c in insp.get_columns("instagram_posts")}
        assert "post_id" in cols
        assert "account" in cols
        assert "created_at" in cols

        # monitoring_events 원본 테이블 컬럼 확인
        cols = {c["name"] for c in insp.get_columns("monitoring_events")}
        assert "schedule_id" in cols
        assert "timestamp" in cols

    def test_archive_has_data(self, db_conn):
        """R: 아카이브 테이블에 데이터 이동 완료 확인"""
        counts = {}
        for tbl in [
            "instagram_posts_archive",
            "monitoring_events_archive",
            "proxy_usage_logs_archive",
            "process_watch_snapshots_archive",
        ]:
            result = db_conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
            counts[tbl] = result

        # instagram_posts_archive: SQLite에서 이관 (22K+)
        assert counts["instagram_posts_archive"] > 0, "instagram_posts_archive 비어있음"
        # monitoring_events_archive: PG에서 이동 (201K)
        assert counts["monitoring_events_archive"] > 0, "monitoring_events_archive 비어있음"
        # proxy_usage_logs_archive: PG에서 이동 (136K)
        assert counts["proxy_usage_logs_archive"] > 0, "proxy_usage_logs_archive 비어있음"

    def test_instagram_hot_has_recent_data(self, db_conn):
        """R: instagram_posts hot 테이블에 최근 데이터 존재"""
        result = db_conn.execute(
            text("SELECT COUNT(*) FROM instagram_posts")
        ).scalar()
        assert result > 0, "instagram_posts hot 테이블 비어있음 (이관 실패)"
