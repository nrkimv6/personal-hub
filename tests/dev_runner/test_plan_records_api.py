"""Plan Records API HTTP 레벨 테스트 (Phase 6)

엔드포인트: /api/v1/plans/records, /api/v1/plans/events
TestClient 사용, test_db_session 픽스처로 격리
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


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
