"""Plan Archive 실행 이력 applied_request_id 필드 TC

엔드포인트: GET /api/v1/plans/records/{id}
TestClient 사용, applied_request_id 필드 검증
"""
import pytest
from datetime import datetime
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(test_db_engine):
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _setup_record_with_event(session, path: str, request_id: int):
    """PlanRecord + plan_archive_analysis_saved PlanEvent 생성."""
    from app.models.plan_record import PlanRecord, PlanEvent
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

    record = PlanRecord(
        filename_hash=_compute_filename_hash(path),
        file_path=path,
        status="archived",
        archived_at=datetime.now(),
        category="feature",
    )
    session.add(record)
    session.flush()

    event = PlanEvent(
        plan_record_id=record.id,
        event_type="plan_archive_analysis_saved",
        detail={"request_id": request_id, "category": "feature"},
    )
    session.add(event)
    session.commit()
    return record


class TestAppliedRequestIdField:

    def test_record_without_analysis_has_null_applied_request_id(self, client, test_db_session):
        """분석 이벤트 없는 record → applied_request_id=null"""
        from app.models.plan_record import PlanRecord
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        record = PlanRecord(
            filename_hash=_compute_filename_hash("/archive/2026-05-06-no-event.md"),
            file_path="/archive/2026-05-06-no-event.md",
            status="archived",
            archived_at=datetime.now(),
        )
        test_db_session.add(record)
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{record.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "applied_request_id" in data
        assert data["applied_request_id"] is None

    def test_record_with_analysis_event_has_applied_request_id(self, client, test_db_session):
        """plan_archive_analysis_saved 이벤트 있으면 applied_request_id 반환"""
        fake_request_id = 9001
        record = _setup_record_with_event(
            test_db_session,
            "/archive/2026-05-06-with-event.md",
            fake_request_id,
        )

        resp = client.get(f"/api/v1/plans/records/{record.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied_request_id"] == fake_request_id

    def test_record_with_multiple_events_uses_latest(self, client, test_db_session):
        """여러 분석 이벤트가 있으면 가장 최신(id 큰) 이벤트의 request_id 사용"""
        from app.models.plan_record import PlanRecord, PlanEvent
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        record = PlanRecord(
            filename_hash=_compute_filename_hash("/archive/2026-05-06-multi-event.md"),
            file_path="/archive/2026-05-06-multi-event.md",
            status="archived",
            archived_at=datetime.now(),
        )
        test_db_session.add(record)
        test_db_session.flush()

        # 첫 번째 이벤트 (request_id=100)
        event1 = PlanEvent(
            plan_record_id=record.id,
            event_type="plan_archive_analysis_saved",
            detail={"request_id": 100},
        )
        test_db_session.add(event1)
        test_db_session.flush()

        # 두 번째 이벤트 (request_id=200, id가 더 큼)
        event2 = PlanEvent(
            plan_record_id=record.id,
            event_type="plan_archive_analysis_saved",
            detail={"request_id": 200},
        )
        test_db_session.add(event2)
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{record.id}")
        assert resp.status_code == 200
        # event2.id > event1.id 이므로 200이 반환돼야 함
        assert resp.json()["applied_request_id"] == 200
