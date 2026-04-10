"""PG 아카이브 검색 API + 배치 이동 TC"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text, inspect

from app.core.database import engine, is_pg
from app.main import app
from app.database import get_db
from app.models.instagram_post_archive import InstagramPostArchive
from app.models.monitoring_event_archive import MonitoringEventArchive


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def skip_if_sqlite():
    """SQLite 환경에서는 archive 검증 스킵."""
    if not is_pg:
        pytest.skip("PostgreSQL 전용 테스트")


# ── Phase T1: ORM 모델 존재 확인 ─────────────────────────────────────────────

class TestArchiveModels:
    """InstagramPostArchive / MonitoringEventArchive 모델 정의 확인."""

    def test_instagram_archive_model_exists(self):
        """R: InstagramPostArchive 모델이 올바른 테이블명을 가진다."""
        assert InstagramPostArchive.__tablename__ == "instagram_posts_archive"

    def test_instagram_archive_model_key_columns(self):
        """R: InstagramPostArchive 주요 컬럼 존재 확인."""
        cols = {c.name for c in InstagramPostArchive.__table__.columns}
        required = {"id", "post_id", "account", "caption", "posted_at", "created_at"}
        assert required.issubset(cols), f"누락 컬럼: {required - cols}"

    def test_monitoring_event_archive_model_exists(self):
        """R: MonitoringEventArchive 모델이 올바른 테이블명을 가진다."""
        assert MonitoringEventArchive.__tablename__ == "monitoring_events_archive"

    def test_monitoring_event_archive_model_key_columns(self):
        """R: MonitoringEventArchive 주요 컬럼 존재 확인."""
        cols = {c.name for c in MonitoringEventArchive.__table__.columns}
        required = {"id", "schedule_id", "timestamp", "status", "event_type"}
        assert required.issubset(cols), f"누락 컬럼: {required - cols}"


# ── Phase T1: Instagram Archive API ──────────────────────────────────────────

@pytest.fixture
def archive_client():
    """instagram archive API 테스트 클라이언트 (PG 직접 연결)."""
    from sqlalchemy.orm import sessionmaker
    from app.core.database import engine as pg_engine

    PgSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    def override_get_db():
        db = PgSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestInstagramArchiveAPI:
    """GET /api/v1/instagram/posts/archive 테스트."""

    def test_get_instagram_archive_posts_200(self, archive_client):
        """R: GET /api/v1/instagram/posts/archive → 200 + PostListResponse 구조."""
        resp = archive_client.get("/api/v1/instagram/posts/archive")
        assert resp.status_code == 200
        body = resp.json()
        assert "posts" in body
        assert "total" in body
        assert "page" in body
        assert "limit" in body

    def test_get_instagram_archive_posts_default_page(self, archive_client):
        """B: 기본 page=1, limit=20 파라미터 반영."""
        resp = archive_client.get("/api/v1/instagram/posts/archive")
        body = resp.json()
        assert body["page"] == 1
        assert body["limit"] == 20

    def test_get_instagram_archive_posts_account_filter(self, archive_client):
        """B: account 필터 파라미터 전달 시 200 응답."""
        resp = archive_client.get("/api/v1/instagram/posts/archive?account=nonexistent_test_account")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0

    def test_get_instagram_archive_posts_date_filter(self, archive_client):
        """B: date_from/date_to 필터 파라미터 전달 시 200 응답."""
        resp = archive_client.get(
            "/api/v1/instagram/posts/archive?date_from=2020-01-01&date_to=2020-01-31"
        )
        assert resp.status_code == 200

    def test_get_instagram_archive_posts_limit(self, archive_client):
        """B: limit 파라미터 반영 확인."""
        resp = archive_client.get("/api/v1/instagram/posts/archive?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5
        assert len(body["posts"]) <= 5


# ── Phase T1: Monitoring Events Archive API ───────────────────────────────────

class TestMonitoringEventsArchiveAPI:
    """GET /api/v1/monitoring/events/archive 테스트."""

    def test_get_monitoring_events_archive_200(self, archive_client):
        """R: GET /api/v1/monitoring/events/archive → 200 + MonitoringEventList 구조."""
        resp = archive_client.get("/api/v1/monitoring/events/archive")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "total_pages" in body

    def test_get_monitoring_events_archive_schedule_filter(self, archive_client):
        """B: schedule_id 필터 파라미터 전달 시 200 응답."""
        resp = archive_client.get("/api/v1/monitoring/events/archive?schedule_id=99999")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0


# ── Phase T1: Batch Script ────────────────────────────────────────────────────

class TestBatchScript:
    """archive_batch_move 스크립트 TC."""

    def test_batch_move_dry_run_no_changes(self):
        """R: dry-run 실행 시 실제 DB 변경 없음."""
        from scripts.archive_batch_move import run_batch
        from sqlalchemy import text as sqla_text

        # dry-run 전 카운트
        with engine.connect() as conn:
            before = conn.execute(sqla_text("SELECT COUNT(*) FROM monitoring_events")).scalar()

        run_batch(cutoff_days=30, dry_run=True)

        # dry-run 후 카운트 동일
        with engine.connect() as conn:
            after = conn.execute(sqla_text("SELECT COUNT(*) FROM monitoring_events")).scalar()

        assert before == after, "dry-run인데 카운트 변경됨"

    def test_batch_move_excludes_fk_referenced(self):
        """E: FK 참조 행은 instagram_posts에서 이동 제외된다."""
        from scripts.archive_batch_move import move_instagram_posts
        from sqlalchemy import text as sqla_text

        # events, uncategorized_posts, popups 테이블에서 참조 중인 id 조회
        with engine.connect() as conn:
            # FK 참조 행이 없는 경우 (혹은 있는 경우) 모두 0건 혹은 FK 제외 확인
            fk_ids_result = conn.execute(sqla_text("""
                SELECT source_instagram_post_id FROM events
                 WHERE source_instagram_post_id IS NOT NULL
                UNION
                SELECT source_instagram_post_id FROM uncategorized_posts
                 WHERE source_instagram_post_id IS NOT NULL
                UNION
                SELECT source_instagram_post_id FROM popups
                 WHERE source_instagram_post_id IS NOT NULL
            """))
            fk_ids = {row[0] for row in fk_ids_result}

        if not fk_ids:
            pytest.skip("FK 참조 instagram_posts 행 없음 (검증 불가)")

        # move_instagram_posts dry-run 결과에서 FK 행이 포함되지 않아야 함
        # (dry-run은 count만 조회)
        cutoff = datetime.now() + timedelta(days=1)  # 모든 행 포함 cutoff
        with engine.begin() as conn:
            count = move_instagram_posts(conn, cutoff=cutoff, dry_run=True)

        with engine.connect() as conn:
            actual_movable = conn.execute(sqla_text("""
                SELECT COUNT(*) FROM instagram_posts
                WHERE id NOT IN (
                    SELECT source_instagram_post_id FROM events WHERE source_instagram_post_id IS NOT NULL
                    UNION
                    SELECT source_instagram_post_id FROM uncategorized_posts WHERE source_instagram_post_id IS NOT NULL
                    UNION
                    SELECT source_instagram_post_id FROM popups WHERE source_instagram_post_id IS NOT NULL
                )
            """)).scalar()

        assert count == actual_movable, "FK 참조 행 제외가 dry-run 결과와 불일치"

    def test_ensure_next_month_partition(self):
        """R: ensure_next_month_partitions 실행 시 에러 없음."""
        from scripts.archive_batch_move import ensure_next_month_partitions
        with engine.begin() as conn:
            # 이미 존재하면 IF NOT EXISTS로 스킵, 에러 없어야 함
            ensure_next_month_partitions(conn, dry_run=False)


# ── Phase T3: 통합 TC ─────────────────────────────────────────────────────────

class TestBatchMoveFullCycle:
    """T3: 실제 PG에서 hot INSERT → 배치 이동 → archive 확인 → hot 감소 확인."""

    TEST_SCHEDULE_ID = 999999  # 존재하지 않는 schedule_id (FK없이 직접 INSERT)

    def setup_method(self):
        """테스트 전: 임시 이벤트 정리."""
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM monitoring_events WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            )
            conn.execute(
                text("DELETE FROM monitoring_events_archive WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            )

    def teardown_method(self):
        """테스트 후: 임시 이벤트 정리."""
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM monitoring_events WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            )
            conn.execute(
                text("DELETE FROM monitoring_events_archive WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            )

    def test_full_cycle(self):
        """T3: 오래된 이벤트 INSERT → archive batch → archive에서 조회 확인."""
        from scripts.archive_batch_move import move_monitoring_events, ensure_next_month_partitions
        from sqlalchemy import text as sqla_text

        # Dec 2025 파티션 사용 (기존 파티션 보장)
        old_ts = datetime(2025, 12, 15, 12, 0, 0)

        # 테스트용 파티션이 없으면 생성 (Dec 2025)
        with engine.begin() as conn:
            conn.execute(sqla_text(
                "CREATE TABLE IF NOT EXISTS monitoring_events_archive_y2025m12 "
                "PARTITION OF monitoring_events_archive "
                "FOR VALUES FROM ('2025-12-01') TO ('2026-01-01')"
            ))

        # 1. hot 테이블에 오래된 이벤트 직접 INSERT
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO monitoring_events
                    (schedule_id, timestamp, event_type, status, available_count)
                VALUES (:sid, :ts, 'check', 'success', 0)
            """), {"sid": self.TEST_SCHEDULE_ID, "ts": old_ts})

        # 2. hot 카운트 확인
        with engine.connect() as conn:
            hot_before = conn.execute(
                text("SELECT COUNT(*) FROM monitoring_events WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            ).scalar()
        assert hot_before >= 1

        # 3. 배치 이동 실행 (30일 이상 오래된 것)
        cutoff = datetime.now() - timedelta(days=30)
        with engine.begin() as conn:
            moved = move_monitoring_events(conn, cutoff=cutoff, dry_run=False)

        assert moved >= 1

        # 4. hot에서 사라졌는지 확인
        with engine.connect() as conn:
            hot_after = conn.execute(
                text("SELECT COUNT(*) FROM monitoring_events WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            ).scalar()
        assert hot_after == 0

        # 5. archive에 있는지 확인
        with engine.connect() as conn:
            archive_count = conn.execute(
                text("SELECT COUNT(*) FROM monitoring_events_archive WHERE schedule_id = :sid"),
                {"sid": self.TEST_SCHEDULE_ID},
            ).scalar()
        assert archive_count >= 1
