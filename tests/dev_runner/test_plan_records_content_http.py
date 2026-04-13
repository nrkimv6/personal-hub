"""Phase T5: HTTP 통합 테스트 — PlanRecord content/restore/ingest/deep-search

GET /api/v1/plans/records/{id}/content
POST /api/v1/plans/records/{id}/restore
GET /api/v1/plans/records?q=keyword&deep=true/false

TestClient 기반 (실서버 불필요).
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/plans/records"


@pytest.fixture(scope="module")
def api_client():
    from app.main import app
    return TestClient(app)


class TestGetRecordContentHTTP:

    def test_http_get_record_content(self, api_client, tmp_path):
        """R: GET /records/{id}/content → 200 + raw_content 필드 반환"""
        from app.database import SessionLocal
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        db = SessionLocal()
        try:
            svc = PlanRecordService(db)
            fp = str(tmp_path / "2026-01-http-content.md")
            content = "# HTTP Content Test\n\nsome body content"
            record = svc.mark_archived(fp, fp, raw_content=content)
            db.commit()
            record_id = record.id
        finally:
            db.close()

        resp = api_client.get(f"{BASE_URL}/{record_id}/content")
        assert resp.status_code == 200, f"응답 코드: {resp.status_code}, 본문: {resp.text}"
        data = resp.json()
        assert data.get("raw_content") == content, f"raw_content 불일치: {data}"

    def test_http_get_record_content_not_found(self, api_client):
        """E: GET /records/999999/content → 404"""
        resp = api_client.get(f"{BASE_URL}/999999/content")
        assert resp.status_code == 404, f"응답 코드: {resp.status_code}"


class TestPostRestoreHTTP:

    def test_http_post_restore(self, api_client, tmp_path):
        """R: POST /records/{id}/restore → 200 + 파일 복원"""
        from app.database import SessionLocal
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        archive_fp = tmp_path / "2026-01-http-restore.md"
        content = "# HTTP Restore Test\n\nbody to restore"

        db = SessionLocal()
        try:
            svc = PlanRecordService(db)
            record = svc.mark_archived(str(archive_fp), str(archive_fp), raw_content=content)
            record.file_removed_at = datetime.now()
            db.commit()
            record_id = record.id
        finally:
            db.close()

        resp = api_client.post(f"{BASE_URL}/{record_id}/restore")
        assert resp.status_code == 200, f"응답 코드: {resp.status_code}, 본문: {resp.text}"

        # 파일이 복원됐는지 확인
        assert archive_fp.exists(), f"복원 파일이 존재해야 함: {archive_fp}"
        assert archive_fp.read_text(encoding="utf-8") == content

    def test_http_post_restore_no_content(self, api_client, tmp_path):
        """E: POST /records/{id}/restore (raw_content=NULL) → 404"""
        from app.database import SessionLocal
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        db = SessionLocal()
        try:
            svc = PlanRecordService(db)
            fp = str(tmp_path / "2026-01-http-no-content.md")
            record = svc.get_or_create(fp)
            # raw_content 없는 상태
            db.commit()
            record_id = record.id
        finally:
            db.close()

        resp = api_client.post(f"{BASE_URL}/{record_id}/restore")
        assert resp.status_code == 404, f"응답 코드: {resp.status_code}"


class TestDeepSearchHTTP:

    def test_http_search_deep_true(self, api_client, tmp_path):
        """R: GET /records?q=keyword&deep=true → raw_content 매칭 결과 포함"""
        from app.database import SessionLocal
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        unique_kw = "HTTP_DEEP_SEARCH_KW_UNIQUE_XYZ_T5"
        fp = str(tmp_path / "2026-01-http-deep.md")

        db = SessionLocal()
        try:
            svc = PlanRecordService(db)
            record = svc.mark_archived(fp, fp, raw_content=f"# Plan\n{unique_kw} in body")
            db.commit()
            record_id = record.id
        finally:
            db.close()

        resp = api_client.get(f"{BASE_URL}?q={unique_kw}&deep=true")
        assert resp.status_code == 200, f"응답 코드: {resp.status_code}"
        data = resp.json()
        records_list = data if isinstance(data, list) else data.get("records", [])
        ids = [r["id"] for r in records_list]
        assert record_id in ids, f"deep=true 검색 결과에 record {record_id} 없음. ids: {ids}"

    def test_http_search_deep_false(self, api_client, tmp_path):
        """B: GET /records?q=keyword (deep 없음, default false) → summary/title만 매칭"""
        from app.database import SessionLocal
        from app.modules.dev_runner.services.plan_record_service import PlanRecordService

        unique_kw = "HTTP_SHALLOW_SEARCH_KW_UNIQUE_XYZ_T5"
        fp = str(tmp_path / "2026-01-http-shallow.md")

        db = SessionLocal()
        try:
            svc = PlanRecordService(db)
            # raw_content에만 키워드, title/summary는 없음
            record = svc.mark_archived(fp, fp, raw_content=f"# Plan\n{unique_kw} in body only")
            db.commit()
            record_id = record.id
        finally:
            db.close()

        resp = api_client.get(f"{BASE_URL}?q={unique_kw}")
        assert resp.status_code == 200, f"응답 코드: {resp.status_code}"
        data = resp.json()
        records_list = data if isinstance(data, list) else data.get("records", [])
        ids = [r["id"] for r in records_list]
        assert record_id not in ids, f"deep=false인데 raw_content 검색으로 record {record_id} 가 나옴. ids: {ids}"
