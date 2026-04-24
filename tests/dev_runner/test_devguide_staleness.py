"""
test_devguide_staleness.py — dev-guide staleness 파이프라인 단위 테스트

Phase T1 TC 7개:
- R: 정상 케이스
- B: 경계값
- E: 에러/방어 케이스

Phase T1 PG guard TC 4개 (추가):
- B/E: PG 연결 오류 시 warning-only, traceback 없음
- R: 비DB 오류는 exc_info=True 유지

Phase T3 TC 2개:
- 실제 _meta.yaml + DB 통합 검증
- requirements_sync 제거 후 pipeline 무결성
"""
import json
import logging
import psycopg2
import sqlalchemy.exc
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.claude_worker.services.plan_analyze_handler import (
    build_devguide_staleness_report,
    save_devguide_staleness_result,
    save_plan_archive_result,
)


# ──────────────────────────────────────────
# fixtures
# ──────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _make_meta(guides: dict) -> dict:
    """테스트용 _meta.yaml 딕셔너리 생성."""
    return guides


def _make_whitelist(*tags: str) -> set:
    return set(tags)


# ──────────────────────────────────────────
# Phase T1: 단위 테스트
# ──────────────────────────────────────────

class TestBuildDevguideStalenessReport:
    """build_devguide_staleness_report() 단위 테스트"""

    def test_build_devguide_staleness_report_right(self, db):
        """R: PlanRecord 5건 (pending 2건 guide-A, 1건 guide-B) → report에 각 가이드 포함"""
        # Arrange: guide-A owns ['pipeline'], guide-B owns ['skill']
        meta = {
            "pipeline-overview": {
                "owns_archive_tags": ["pipeline"],
                "last_archive_scan": "2026-01-01",
            },
            "skill-guide": {
                "owns_archive_tags": ["skill"],
                "last_archive_scan": "2026-01-01",
            },
        }
        whitelist = _make_whitelist("pipeline", "skill", "agent")

        last_scan = datetime(2026, 1, 1)
        after_scan = last_scan + timedelta(days=1)

        # pipeline 파일 2개 (guide-A)
        for i in range(2):
            db.add(PlanRecord(
                filename_hash=f"pipeline_{i}",
                file_path=f"docs/archive/2026-01-{i+2:02d}_pipeline-fix.md",
                archived_at=after_scan,
                summary=f"pipeline summary {i}",
            ))
        # skill 파일 1개 (guide-B)
        db.add(PlanRecord(
            filename_hash="skill_0",
            file_path="docs/archive/2026-01-03_skill-refactor.md",
            archived_at=after_scan,
            summary="skill summary",
        ))
        # before_scan 파일 (이미 스캔됨 → pending 아님)
        db.add(PlanRecord(
            filename_hash="old_pipeline",
            file_path="docs/archive/2025-12-01_pipeline-old.md",
            archived_at=last_scan - timedelta(days=1),
            summary="old",
        ))
        db.commit()

        with patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta), \
             patch("app.shared.wiki_tags.load_whitelist", return_value=whitelist), \
             patch("app.shared.wiki_tags.extract_wiki_tags",
                   side_effect=lambda fn, wl: ["pipeline"] if "pipeline" in fn else (["skill"] if "skill" in fn else ["untagged"])):
            report = build_devguide_staleness_report(db)

        guides = {r["guide"]: r for r in report}
        assert "pipeline-overview" in guides
        assert guides["pipeline-overview"]["pending_count"] == 2
        assert "skill-guide" in guides
        assert guides["skill-guide"]["pending_count"] == 1

    def test_build_devguide_staleness_report_boundary_no_pending(self, db):
        """B: 모든 가이드 pending=0 → 빈 리스트 반환"""
        meta = {
            "pipeline-overview": {
                "owns_archive_tags": ["pipeline"],
                "last_archive_scan": "2026-04-10",  # 최신 스캔
            },
        }
        whitelist = _make_whitelist("pipeline")

        # 스캔 이전 파일만
        db.add(PlanRecord(
            filename_hash="old_1",
            file_path="docs/archive/2026-01-01_pipeline-old.md",
            archived_at=datetime(2026, 1, 1),
            summary="old",
        ))
        db.commit()

        with patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta), \
             patch("app.shared.wiki_tags.load_whitelist", return_value=whitelist), \
             patch("app.shared.wiki_tags.extract_wiki_tags",
                   side_effect=lambda fn, wl: ["pipeline"] if "pipeline" in fn else ["untagged"]):
            report = build_devguide_staleness_report(db)

        assert report == [], f"pending 없으면 빈 리스트여야 함, got: {report}"


class TestSaveDevguideStalenessResult:
    """save_devguide_staleness_result() 단위 테스트"""

    def test_save_devguide_staleness_result_right(self, db):
        """R: report 입력 → PlanEvent(event_type="devguide_staleness") DB 저장 확인"""
        report = [
            {
                "guide": "pipeline-overview",
                "pending_count": 3,
                "pending_archives": [
                    {"file_path": "docs/archive/2026-01-01_test.md", "summary": "test"},
                ],
            }
        ]

        save_devguide_staleness_result(db, report)

        event = db.query(PlanEvent).filter_by(event_type="devguide_staleness").first()
        assert event is not None
        assert event.plan_record_id is None  # 시스템 이벤트
        assert event.detail["guides"][0]["guide"] == "pipeline-overview"
        assert event.detail["guides"][0]["pending_count"] == 3


class TestFlagGuideStalenessTrigger:
    """_maybe_flag_guide_staleness() 단위 테스트"""

    def test_flag_guide_staleness_on_archive_analyze_right(self, db):
        """R: save_plan_archive_result() 완료 후 매칭 가이드에 pending 4건 → PlanEvent 생성"""
        meta = {
            "pipeline-overview": {
                "owns_archive_tags": ["pipeline"],
                "last_archive_scan": "2026-01-01",
            },
        }
        whitelist = _make_whitelist("pipeline")
        last_scan = datetime(2026, 1, 1)

        # pending 4건 (threshold=3 초과)
        for i in range(4):
            db.add(PlanRecord(
                filename_hash=f"pending_{i}",
                file_path=f"docs/archive/2026-01-{i+2:02d}_pipeline-fix.md",
                archived_at=last_scan + timedelta(days=1),
            ))
        db.commit()

        with patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta), \
             patch("app.shared.wiki_tags.load_whitelist", return_value=whitelist), \
             patch("app.shared.wiki_tags.extract_wiki_tags",
                   side_effect=lambda fn, wl: ["pipeline"] if "pipeline" in fn else ["untagged"]):
            from app.modules.claude_worker.services.plan_analyze_handler import _maybe_flag_guide_staleness
            result = _maybe_flag_guide_staleness(db, "docs/archive/2026-01-10_pipeline-new.md")

        assert result is True
        event = db.query(PlanEvent).filter_by(event_type="devguide_staleness").first()
        assert event is not None
        assert event.detail["guide"] == "pipeline-overview"

    def test_flag_guide_staleness_threshold_boundary(self, db):
        """B: pending 2건(threshold 미만) → PlanEvent 미생성, pending 3건(정확히) → PlanEvent 생성"""
        meta = {
            "pipeline-overview": {
                "owns_archive_tags": ["pipeline"],
                "last_archive_scan": "2026-01-01",
            },
        }
        whitelist = _make_whitelist("pipeline")
        last_scan = datetime(2026, 1, 1)

        # 먼저 2건으로 확인
        for i in range(2):
            db.add(PlanRecord(
                filename_hash=f"boundary_{i}",
                file_path=f"docs/archive/2026-01-{i+2:02d}_pipeline-fix.md",
                archived_at=last_scan + timedelta(days=1),
            ))
        db.commit()

        extract_mock = lambda fn, wl: ["pipeline"] if "pipeline" in fn else ["untagged"]

        with patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta), \
             patch("app.shared.wiki_tags.load_whitelist", return_value=whitelist), \
             patch("app.shared.wiki_tags.extract_wiki_tags", side_effect=extract_mock):
            from app.modules.claude_worker.services.plan_analyze_handler import _maybe_flag_guide_staleness
            result_below = _maybe_flag_guide_staleness(db, "docs/archive/2026-01-10-pipeline-check.md")

        assert result_below is False
        assert db.query(PlanEvent).filter_by(event_type="devguide_staleness").count() == 0

        # 3건으로 증가
        db.add(PlanRecord(
            filename_hash="boundary_2",
            file_path="docs/archive/2026-01-04_pipeline-fix.md",
            archived_at=last_scan + timedelta(days=1),
        ))
        db.commit()

        with patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta), \
             patch("app.shared.wiki_tags.load_whitelist", return_value=whitelist), \
             patch("app.shared.wiki_tags.extract_wiki_tags", side_effect=extract_mock):
            from app.modules.claude_worker.services.plan_analyze_handler import _maybe_flag_guide_staleness
            result_at = _maybe_flag_guide_staleness(db, "docs/archive/2026-01-10-pipeline-check.md")

        assert result_at is True
        assert db.query(PlanEvent).filter_by(event_type="devguide_staleness").count() == 1

    def test_flag_guide_staleness_error_no_meta(self, db):
        """E: _meta.yaml 로드 실패 시 → 예외 발생하지 않고 False 반환 (방어적)"""
        with patch(
            "app.shared.wiki_tags.load_meta_yaml",
            side_effect=FileNotFoundError("_meta.yaml not found"),
        ):
            from app.modules.claude_worker.services.plan_analyze_handler import _maybe_flag_guide_staleness
            result = _maybe_flag_guide_staleness(db, "docs/archive/2026-01-01_test.md")

        assert result is False


# ──────────────────────────────────────────
# Phase T3: 통합 TC
# ──────────────────────────────────────────

class TestDevguideStalenessIntegration:
    """재현/통합 TC — save_plan_archive_result 파이프라인 무결성"""

    def test_requirements_sync_removal_no_regression(self, db):
        """T3: requirements sync 함수 제거 후 save_plan_archive_result() → detect_recurrence까지 정상 동작"""
        import json as _json

        # Arrange: scope 겹침 기존 record
        existing = PlanRecord(
            filename_hash="existing_hash_abc",
            file_path="docs/archive/2026-01-01_existing.md",
            category="naver-booking",
            scope=_json.dumps(["plan_service.py"]),
            applied_at=datetime(2026, 1, 1),
            intent="기존 버그",
            plan_date=datetime(2026, 1, 1).date(),
            llm_processed_at=datetime(2026, 1, 1),
        )
        db.add(existing)
        # 현재 archive될 record
        current = PlanRecord(
            filename_hash="current_hash_xyz",
            file_path="docs/archive/2026-04-10_current.md",
            archived_at=datetime(2026, 4, 10),
        )
        db.add(current)
        db.commit()

        mock_req = MagicMock()
        mock_req.caller_id = "current_hash_xyz"
        result = {
            "success": True,
            "result": {
                "category": "naver-booking",
                "tags": ["fix"],
                "summary": "현재 버그 수정",
                "intent": "버그 수정",
                "scope": ["plan_service.py"],
            },
            "raw_response": "",
        }

        # _maybe_flag_guide_staleness와 _maybe_queue_requirements_sync 모두 mock
        with patch("app.modules.claude_worker.services.plan_analyze_handler._maybe_flag_guide_staleness", return_value=False), \
             patch("app.modules.claude_worker.services.plan_analyze_handler._maybe_queue_requirements_sync", return_value=False):
            # Act: 예외 없이 완료되어야 함
            save_plan_archive_result(db, mock_req, result)

        # Assert: DB 정상 갱신
        updated = db.query(PlanRecord).filter_by(filename_hash="current_hash_xyz").first()
        assert updated is not None
        assert updated.category == "naver-booking"
        assert updated.summary == "현재 버그 수정"


# ========== Phase T4: E2E (TestClient) ==========

@pytest.fixture(scope="module")
def api_client_staleness(test_db_engine):
    """TestClient + test_db_engine 오버라이드 (staleness)"""
    from app.main import app
    from app.database import get_db
    from fastapi.testclient import TestClient
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


def test_e2e_guide_status_with_history(api_client_staleness):
    """T4: GET /api/v1/plans/records/guide-status?include_history=true → 200 + staleness_history 필드"""
    resp = api_client_staleness.get("/api/v1/plans/records/guide-status?include_history=true")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "guide" in item
        assert "staleness_history" in item
        assert isinstance(item["staleness_history"], list)


# ========== Phase T5: HTTP 통합 (http_live) ==========

import pytest as _pytest


@_pytest.mark.http_live
def test_http_guide_status_history():
    """T5: GET /api/v1/plans/records/guide-status?include_history=true → 200 + staleness_history 배열"""
    import httpx
    try:
        resp = httpx.get(
            "http://localhost:8001/api/v1/plans/records/guide-status?include_history=true",
            timeout=10,
        )
    except httpx.ConnectError:
        _pytest.fail("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "staleness_history" in item


@_pytest.mark.http_live
def test_http_schedule_run_devguide_staleness():
    """T5: GET /api/tasks/schedules → devguide_staleness target_type 존재 또는 plan_requirements_sync 미존재"""
    import httpx
    try:
        resp = httpx.get("http://localhost:8001/api/tasks/schedules", timeout=10)
    except httpx.ConnectError:
        _pytest.fail("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    # devguide_staleness 타입 스케줄 존재 확인 (또는 requirements_sync 미존재)
    if isinstance(data, list):
        target_types = [item.get("target_type") for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        items = data.get("items") or data.get("schedules") or data.get("data") or []
        target_types = [item.get("target_type") for item in items if isinstance(item, dict)]
    else:
        target_types = []
    assert "plan_requirements_sync" not in target_types or "devguide_staleness" in target_types


# ──────────────────────────────────────────────────────────────────
# Phase T1 PG guard TC — is_connection_error() guard 계약 검증
# ──────────────────────────────────────────────────────────────────

def _make_db_commit_error(error):
    """db mock: query().filter_by().first() → MagicMock record, commit raises error."""
    db = MagicMock()
    record_mock = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = record_mock
    db.commit.side_effect = error
    return db


def test_save_plan_archive_result_pg_connection_error_no_traceback(caplog):
    """B: save_plan_archive_result에서 psycopg2.OperationalError → warning 1회, traceback 없음."""
    db = _make_db_commit_error(psycopg2.OperationalError("could not connect to server"))
    request = MagicMock()
    request.caller_id = "deadbeef1234"

    with caplog.at_level(logging.DEBUG):
        result = save_plan_archive_result(db, request, {"result": {"category": "infra"}, "success": True})

    assert result is False
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) == 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0
    db.rollback.assert_called_once()


def test_build_devguide_staleness_report_pg_connection_error_no_traceback(caplog):
    """B: build_devguide_staleness_report에서 PG 연결 오류 → warning 1회, traceback 없음."""
    pg_err = psycopg2.OperationalError("could not connect to server")
    db = MagicMock()

    with patch(
        "app.modules.dev_runner.services.plan_record_service.PlanRecordService.get_guide_status",
        side_effect=pg_err,
    ), caplog.at_level(logging.DEBUG):
        result = build_devguide_staleness_report(db)

    assert result == []
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) == 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0


def test_save_devguide_staleness_result_pg_connection_error_no_traceback(caplog):
    """B: save_devguide_staleness_result DB commit 실패(PG) → warning 1회, rollback, traceback 없음."""
    db = MagicMock()
    db.commit.side_effect = psycopg2.OperationalError("could not connect to server")

    with caplog.at_level(logging.DEBUG):
        result = save_devguide_staleness_result(db, [{"guide": "g1", "pending_count": 3}])

    assert result is False
    pg_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "connection error" in r.message]
    assert len(pg_warnings) == 1
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) == 0
    db.rollback.assert_called_once()


def test_save_plan_archive_result_non_pg_error_preserves_exc_info(caplog):
    """R: save_plan_archive_result에서 비DB 오류(ValueError) → exc_info=True traceback 유지."""
    db = _make_db_commit_error(ValueError("unexpected schema error"))
    request = MagicMock()
    request.caller_id = "deadbeef5678"

    with caplog.at_level(logging.DEBUG):
        result = save_plan_archive_result(db, request, {"result": {}, "success": True})

    assert result is False
    error_with_traceback = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert len(error_with_traceback) >= 1
    pg_warnings = [r for r in caplog.records if "connection error" in r.message]
    assert len(pg_warnings) == 0
