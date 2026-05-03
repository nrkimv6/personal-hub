"""Plan Records API HTTP 레벨 테스트 (Phase 6)

엔드포인트: /api/v1/plans/records, /api/v1/plans/events
TestClient 사용, test_db_session 픽스처로 격리
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


pytestmark = pytest.mark.http


@pytest.fixture(scope="module")
def test_db_engine(tmp_path_factory):
    """Plan records API 전용 SQLite 엔진.

    이 모듈은 plan_records/plan_events만 직접 검증하므로, 세션 범위 전체 모델
    create_all을 타지 않게 해서 전역 테스트 DB 부트스트랩 timeout을 피한다.
    """
    from sqlalchemy import create_engine, event
    from app.models.base import Base
    from app.models.plan_record import PlanEvent, PlanRecord
    from app.models.tracking_item import TrackingItem, TrackingItemPlanLink

    db_path = tmp_path_factory.mktemp("plan_records_api_db") / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        bind=engine,
        tables=[
            PlanRecord.__table__,
            PlanEvent.__table__,
            TrackingItem.__table__,
            TrackingItemPlanLink.__table__,
        ],
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def client(test_db_engine):
    """TestClient (module scope) + test_db_engine 오버라이드

    module scope: 모듈당 1회 TestClient 생성/소멸 → lifespan 반복 없음.
    get_db는 요청마다 engine에서 새 세션을 생성하여 반환.
    테스트 데이터는 test_db_session.commit() 후 클라이언트에서 조회 가능.
    """
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


def _make_record(session, path, **kwargs):
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService
    svc = PlanRecordService(session)
    r = svc.get_or_create(path, **kwargs)
    session.flush()
    return r


class TestPlanRecordsApiDbBootstrap:
    """Plan records API 전용 DB fixture 계약."""

    def test_plan_records_bootstrap_right_creates_required_tables(self, test_db_engine):
        from sqlalchemy import inspect

        tables = set(inspect(test_db_engine).get_table_names())

        assert "plan_records" in tables
        assert "plan_events" in tables
        assert "tracking_items" in tables
        assert "tracking_item_plan_links" in tables

    def test_plan_records_bootstrap_right_supports_event_fk(self, test_db_session):
        from app.models.plan_record import PlanEvent, PlanRecord

        record = PlanRecord(
            filename_hash="bootstrap_contract_001",
            file_path="/plan/2026-05-03-bootstrap-contract.md",
            title="Bootstrap Contract",
        )
        test_db_session.add(record)
        test_db_session.flush()

        event = PlanEvent(plan_record_id=record.id, event_type="created")
        test_db_session.add(event)
        test_db_session.commit()

        saved = test_db_session.query(PlanEvent).filter_by(id=event.id).one()
        assert saved.record.id == record.id


# ========== /api/v1/plans/records ==========

class TestListRecords:

    def test_list_records_empty(self, client):
        """빈 배열 반환"""
        resp = client.get("/api/v1/plans/records?project=__nonexistent_project__")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_records_with_pagination(self, client, test_db_session):
        """skip/limit 파라미터 정상 처리"""
        for i in range(5):
            _make_record(test_db_session, f"/plan/2026-03-{i+1:02d}-paging.md", project="paging_test")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?project=paging_test&skip=0&limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

        resp2 = client.get("/api/v1/plans/records?project=paging_test&skip=3&limit=3")
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), list)

    def test_list_records_filter_by_project(self, client, test_db_session):
        """project 필터"""
        _make_record(test_db_session, "/plan/2026-03-06-alpha.md", project="proj-alpha-http")
        _make_record(test_db_session, "/plan/2026-03-07-beta.md", project="proj-beta-http")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?project=proj-alpha-http")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(r["project"] == "proj-alpha-http" for r in data)

    def test_list_records_filter_by_status(self, client, test_db_session):
        """status 필터"""
        r = _make_record(test_db_session, "/plan/2026-03-08-status.md")
        r.status = "구현중"
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?status=구현중")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item["status"] == "구현중" for item in data)


class TestGetRecord:

    def test_get_record_with_events(self, client, test_db_session):
        """특정 record + events 포함 반환"""
        r = _make_record(test_db_session, "/plan/2026-03-09-detail.md", title="HTTP Detail Plan")
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == r.id
        assert data["title"] == "HTTP Detail Plan"
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_get_record_not_found(self, client):
        """존재하지 않는 id → 404"""
        resp = client.get("/api/v1/plans/records/99999")
        assert resp.status_code == 404


class TestMemoUpdate:

    def test_memo_draft_save(self, client, test_db_session):
        """draft 저장 → memo_draft 갱신"""
        r = _make_record(test_db_session, "/plan/2026-03-10-draft.md")
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "draft", "text": "임시 저장 내용"}
        )
        assert resp.status_code == 200
        assert resp.json()["memo_draft"] == "임시 저장 내용"

    def test_memo_confirm(self, client, test_db_session):
        """memo 확정 → memo 갱신, memo_draft 초기화"""
        r = _make_record(test_db_session, "/plan/2026-03-11-confirm.md")
        r.memo_draft = "확정할 내용"
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "confirm"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["memo"] == "확정할 내용"
        assert data["memo_draft"] is None

    def test_memo_rollback(self, client, test_db_session):
        """롤백 → memo_draft를 확정 memo로 되돌림"""
        r = _make_record(test_db_session, "/plan/2026-03-12-rollback.md")
        r.memo = "확정 memo"
        r.memo_draft = "미확정"
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "rollback"}
        )
        assert resp.status_code == 200
        assert resp.json()["memo_draft"] == "확정 memo"

    def test_memo_invalid_action(self, client, test_db_session):
        """잘못된 action → 400"""
        r = _make_record(test_db_session, "/plan/2026-03-13-invalid.md")
        test_db_session.commit()

        resp = client.patch(
            f"/api/v1/plans/records/{r.id}/memo",
            json={"action": "invalid_action"}
        )
        assert resp.status_code == 400

    def test_memo_record_not_found(self, client):
        """존재하지 않는 record → 404"""
        resp = client.patch(
            "/api/v1/plans/records/99999/memo",
            json={"action": "draft", "text": "test"}
        )
        assert resp.status_code == 404


class TestSyncEndpoint:

    def test_sync_endpoint(self, client):
        """동기화 엔드포인트 → 정상 응답"""
        mock_svc_paths = []
        with patch(
            "app.modules.dev_runner.routes.plan_records._plan_service.list_registered_paths",
            return_value=mock_svc_paths
        ):
            resp = client.post("/api/v1/plans/records/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert "created" in data
        assert "updated" in data
        assert "missing" in data


# ========== /api/v1/plans/events ==========

class TestListEvents:

    def test_list_events_empty(self, client):
        """이벤트 없으면 빈 배열"""
        resp = client.get("/api/v1/plans/events?event_type=__nonexistent_type_xyz__")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_events_with_filters(self, client, test_db_session):
        """event_type 필터 동작"""
        _make_record(test_db_session, "/plan/2026-03-14-event.md")
        test_db_session.commit()

        resp = client.get("/api/v1/plans/events?event_type=created")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert all(e["event_type"] == "created" for e in data)

    def test_list_events_pagination(self, client):
        """skip/limit 파라미터 정상 처리"""
        resp = client.get("/api/v1/plans/events?skip=0&limit=10")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ========== /api/v1/plans/records/by-path ==========

class TestGetRecordByPath:

    def test_get_or_create_by_path(self, client):
        """file_path로 get_or_create → 레코드 반환"""
        resp = client.get("/api/v1/plans/records/by-path?file_path=/plan/2026-03-15-by-path.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_path"] == "/plan/2026-03-15-by-path.md"
        assert data["id"] is not None


# ========== /api/v1/plans/records/ingest ==========

class TestIngestSingleRecord:

    def test_ingest_single_updates_existing_record_archive_path_http(self, client, test_db_session):
        """POST /records/ingest updates existing filename-hash record to archive path."""
        from app.models.plan_record import PlanRecord
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        plan_path = "/workspace/docs/plan/2026-05-03_http-archive-path.md"
        archive_path = "/workspace/docs/archive/2026-05-03_http-archive-path.md"
        filename_hash = _compute_filename_hash(plan_path)
        test_db_session.query(PlanRecord).filter_by(filename_hash=filename_hash).delete(synchronize_session=False)
        test_db_session.commit()

        record = PlanRecord(
            filename_hash=filename_hash,
            file_path=plan_path,
            title="Old HTTP Plan",
            project="monitor-page",
            status="planned",
            raw_content="# Old HTTP Plan",
        )
        test_db_session.add(record)
        test_db_session.commit()

        resp = client.post(
            "/api/v1/plans/records/ingest",
            json={
                "file_path": archive_path,
                "project": "monitor-page",
                "raw_content": "# Archived HTTP Plan\n\nnew body",
                "title": "Archived HTTP Plan",
                "status": "archived",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == record.id
        assert data["filename_hash"] == filename_hash
        assert data["file_path"] == archive_path
        assert data["file_path"] != plan_path

        content_resp = client.get(f"/api/v1/plans/records/{record.id}/content")
        assert content_resp.status_code == 200
        assert content_resp.json()["raw_content"] == "# Archived HTTP Plan\n\nnew body"


# ========== Phase T4: import-archived + category/tags 필터 ==========

class TestImportArchived:

    def test_import_archived_endpoint(self, client, tmp_path):
        """POST /api/v1/plans/records/import-archived → 200 + created/updated/... 응답"""
        d = tmp_path / "archive" / "naver-booking"
        d.mkdir(parents=True)
        (d / "2026-02-01_t4-plan-a.md").write_text("# T4 Plan A\ncontent", encoding="utf-8")
        (d / "2026-02-02_t4-plan-b.md").write_text("# T4 Plan B\ncontent", encoding="utf-8")

        resp = client.post(
            f"/api/v1/plans/records/import-archived?archive_dir={tmp_path / 'archive'}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "created" in data
        assert "updated" in data
        assert "skipped" in data
        assert "errors" in data
        assert data["created"] >= 2

    def test_import_archived_no_dir(self, client, tmp_path):
        """POST /api/v1/plans/records/import-archived (존재하지 않는 경로) → 200 + errors 포함"""
        resp = client.post(
            "/api/v1/plans/records/import-archived?archive_dir=/nonexistent/path/archive"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" in data
        assert data["created"] == 0

    def test_list_records_category_filter_http(self, client, test_db_session):
        """GET /api/v1/plans/records?category=instagram → 해당 카테고리만 반환"""
        from app.models.plan_record import PlanRecord
        from datetime import datetime
        test_db_session.query(PlanRecord).filter_by(filename_hash="t4_instagram_001").delete(synchronize_session=False)
        test_db_session.commit()
        r = PlanRecord(
            filename_hash="t4_instagram_001",
            file_path="/archive/instagram/2026-02-10_t4-insta.md",
            project="instagram",
            category="instagram",
            archived_at=datetime.now(),
            status="archived",
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?category=instagram")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert all(item["category"] == "instagram" for item in data)

    def test_list_records_tags_filter_http(self, client, test_db_session):
        """GET /api/v1/plans/records?tags=feat,fix → 태그 포함 레코드만 반환"""
        from app.models.plan_record import PlanRecord
        from datetime import datetime
        test_db_session.query(PlanRecord).filter_by(filename_hash="t4_tags_feat_001").delete(synchronize_session=False)
        test_db_session.commit()
        r = PlanRecord(
            filename_hash="t4_tags_feat_001",
            file_path="/archive/common/2026-02-11_t4-tagged.md",
            project="common",
            category="common",
            tags=["feat", "fix"],
            archived_at=datetime.now(),
            status="archived",
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get("/api/v1/plans/records?tags=feat")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item.get("tags") and "feat" in item["tags"] for item in data)


# ========== Phase T5: 신규 intent/scope 필드 응답 검증 ==========

class TestIntentFieldsInResponse:
    """Phase 8 T5: API 응답에 intent/trigger/scope/plan_date/applied_at 포함 확인"""

    def test_records_api_right_new_fields_in_response(self, client, test_db_session):
        """record에 intent/trigger/scope/plan_date/applied_at 데이터 있을 때 API 응답에 5개 필드 포함"""
        import json
        from datetime import date, datetime
        from app.models.plan_record import PlanRecord
        test_db_session.query(PlanRecord).filter_by(filename_hash="t5_intent_fields_001").delete(synchronize_session=False)
        test_db_session.commit()

        r = PlanRecord(
            filename_hash="t5_intent_fields_001",
            file_path="/archive/monitor/2026-03-20_t5-intent.md",
            project="monitor-t5",
            status="archived",
            archived_at=datetime(2026, 3, 20, 12, 0),
            intent="네이버 예약 스나이핑 재시도 로직 버그를 수정한다.",
            trigger="bug_recurrence",
            scope=json.dumps(["naver_booking", "worker/orchestrator.py"], ensure_ascii=False),
            plan_date=date(2026, 3, 15),
            applied_at=datetime(2026, 3, 20, 13, 52),
        )
        test_db_session.add(r)
        test_db_session.commit()

        # 단건 조회로 5개 필드 확인
        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["intent"] == "네이버 예약 스나이핑 재시도 로직 버그를 수정한다."
        assert data["trigger"] == "bug_recurrence"
        assert data["scope"] == ["naver_booking", "worker/orchestrator.py"]
        assert data["plan_date"] == "2026-03-15"
        assert data["applied_at"] is not None and "2026-03-20" in data["applied_at"]

    def test_records_api_boundary_null_fields_returned_as_none(self, client, test_db_session):
        """값 없는 레코드 조회 → 5개 신규 필드 모두 null로 반환 (500 아님)"""
        from datetime import datetime
        from app.models.plan_record import PlanRecord
        test_db_session.query(PlanRecord).filter_by(filename_hash="t5_null_fields_001").delete(synchronize_session=False)
        test_db_session.commit()

        r = PlanRecord(
            filename_hash="t5_null_fields_001",
            file_path="/archive/monitor/2026-03-21_t5-null.md",
            project="monitor-t5-null",
            status="archived",
            archived_at=datetime(2026, 3, 21, 9, 0),
            # intent, trigger, scope, plan_date, applied_at 모두 미설정
        )
        test_db_session.add(r)
        test_db_session.commit()

        resp = client.get(f"/api/v1/plans/records/{r.id}")
        assert resp.status_code == 200, f"500이 아닌 200이어야 함: {resp.text}"
        data = resp.json()

        assert data["intent"] is None
        assert data["trigger"] is None
        assert data["scope"] is None
        assert data["plan_date"] is None
        assert data["applied_at"] is None


class TestGetOrCreateDefaultStatus:
    """Phase 4: get_or_create 기본 status=planned 검증"""

    def test_get_or_create_default_status_planned(self, test_db_session):
        """신규 생성 시 status='planned' 자동 설정 (RIGHT)"""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        svc = PlanRecordService(test_db_session)
        record = svc.get_or_create(
            "/plan/monitor/2026-03-30_test-default-status.md",
            title="Default Status Test",
            project="monitor",
        )
        test_db_session.flush()
        assert record.status == "planned", f"status는 'planned'이어야 함, 실제: {record.status}"

    def test_get_or_create_existing_record_status_unchanged(self, test_db_session):
        """기존 레코드 조회 시 status 변경 없음 (기존 status 유지)"""
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService
        from app.models.plan_record import PlanRecord as PlanRecordModel
        from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash

        path = "/plan/monitor/2026-03-30_test-existing-status.md"
        # 기존 레코드 직접 삽입 (status='in_progress')
        existing = PlanRecordModel(
            filename_hash=_compute_filename_hash(path),
            file_path=path,
            title="Existing",
            project="monitor",
            status="in_progress",
        )
        test_db_session.add(existing)
        test_db_session.flush()

        svc = PlanRecordService(test_db_session)
        record = svc.get_or_create(path)
        assert record.status == "in_progress", "기존 레코드 status는 변경되지 않아야 함"
