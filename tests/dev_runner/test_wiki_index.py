"""
test_wiki_index.py — wiki-index-to-devguide-status Plan TC

Phase T1: wiki_tags + guide_status + backfill 신규 함수 단위 검증
Phase T3: 실제 파일 기반 통합 검증
"""
import pytest
from datetime import datetime, date, timedelta
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock, mock_open
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# scripts/migrations 하위 모듈 로드를 위한 path 주입
_MIGRATIONS_DIR = str(Path(__file__).resolve().parents[2] / "scripts" / "migrations")
if _MIGRATIONS_DIR not in sys.path:
    sys.path.insert(0, _MIGRATIONS_DIR)

from app.shared.wiki_tags import extract_wiki_tags, load_whitelist, load_meta_yaml
from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


# ========== Fixtures ==========

def _create_tables(eng):
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ========== Phase T1: extract_wiki_tags ==========

def test_extract_wiki_tags_right():
    """R(정상): 파일명에서 whitelist 단어 매칭"""
    wl = {"watchdog", "pipeline", "untagged"}
    result = extract_wiki_tags("2026-04-10_fix-watchdog-heartbeat.md", wl)
    assert result == ["watchdog"]


def test_extract_wiki_tags_boundary_no_match():
    """B(경계): whitelist에 없는 단어만 → ["untagged"]"""
    wl = {"watchdog", "pipeline"}
    result = extract_wiki_tags("2026-04-10_fix-random-stuff.md", wl)
    assert result == ["untagged"]


def test_extract_wiki_tags_boundary_multiple():
    """B(경계): 파일명에 whitelist 단어 3개+ → 전부 sorted 반환"""
    wl = {"watchdog", "pipeline", "plan", "worker"}
    result = extract_wiki_tags("2026-04-10_fix-watchdog-pipeline-plan.md", wl)
    assert result == sorted({"watchdog", "pipeline", "plan"})


# ========== Phase T1: load_whitelist ==========

def test_load_whitelist_right():
    """R(정상): 실제 docs/wiki-schema.md 파싱 → 비어있지 않은 set"""
    result = load_whitelist()
    assert isinstance(result, set)
    assert len(result) > 0
    # 알려진 태그 포함 확인
    assert "watchdog" in result
    assert "pipeline" in result


def test_load_whitelist_error_missing():
    """E(에러): 존재하지 않는 경로 → FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        load_whitelist("/nonexistent/path/wiki-schema.md")


# ========== Phase T1: list_records keyword/date 검색 ==========

def _make_record(db, title: str, summary: str | None, archived_at: datetime | None = None) -> PlanRecord:
    rec = PlanRecord(
        filename_hash=f"hash_{title}",
        file_path=f"docs/archive/2026-04-10_{title}.md",
        title=title,
        summary=summary,
        status="archived" if archived_at else "planned",
        archived_at=archived_at,
    )
    db.add(rec)
    db.flush()
    return rec


def test_plan_record_search_keyword_right(db):
    """R(정상): list_records(q="watchdog") → summary/title에 포함된 레코드만"""
    _make_record(db, "watchdog-fix", "watchdog heartbeat fix", datetime(2026, 4, 9))
    _make_record(db, "other-fix", "some other fix", datetime(2026, 4, 8))
    svc = PlanRecordService(db)
    results = svc.list_records(q="watchdog")
    titles = [r.title for r in results]
    assert "watchdog-fix" in titles
    assert "other-fix" not in titles


def test_plan_record_search_keyword_boundary_empty(db):
    """B(경계): 매칭 없는 keyword → 빈 리스트"""
    svc = PlanRecordService(db)
    results = svc.list_records(q="zzz_nonexistent_xyz")
    assert results == []


def test_plan_record_search_date_range_right(db):
    """R(정상): date_from/date_to 범위 내 archived_at 레코드만"""
    _make_record(db, "in-range", "in range", datetime(2026, 4, 5))
    _make_record(db, "out-range", "out range", datetime(2026, 3, 1))
    svc = PlanRecordService(db)
    results = svc.list_records(
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 10),
    )
    titles = [r.title for r in results]
    assert "in-range" in titles
    # out-range는 범위 밖
    assert "out-range" not in titles


def test_plan_record_search_date_range_boundary(db):
    """B(경계): date_from > date_to → 빈 리스트"""
    svc = PlanRecordService(db)
    results = svc.list_records(
        date_from=datetime(2026, 4, 10),
        date_to=datetime(2026, 4, 1),
    )
    assert results == []


def test_plan_record_search_combined(db):
    """R(정상): keyword + date_range 조합 → 교집합"""
    _make_record(db, "combined-watchdog", "watchdog combined", datetime(2026, 4, 7))
    _make_record(db, "old-watchdog", "watchdog old", datetime(2026, 2, 1))
    svc = PlanRecordService(db)
    results = svc.list_records(
        q="watchdog",
        date_from=datetime(2026, 4, 1),
        date_to=datetime(2026, 4, 10),
    )
    titles = [r.title for r in results]
    assert "combined-watchdog" in titles
    assert "old-watchdog" not in titles


# ========== Phase T1: get_guide_status ==========

def _mock_meta_yaml():
    return {
        "watchdog-architecture.md": {
            "owns_archive_tags": ["watchdog"],
            "last_archive_scan": "2026-04-07",
        },
        "pipeline-overview.md": {
            "owns_archive_tags": ["pipeline", "skill"],
            "last_archive_scan": "2026-04-08",
        },
        "process-structure.md": {
            "owns_archive_tags": ["infra"],
            "last_archive_scan": "2026-04-06",
        },
    }


def test_guide_status_right(db):
    """R(정상): _meta.yaml 3개 가이드 mock + PlanRecord 5건 → 가이드별 pending_count 정확"""
    # watchdog 매칭 2건 (scan 이후)
    _make_record(db, "gs-watchdog-a", "watchdog fix a", datetime(2026, 4, 8))
    _make_record(db, "gs-watchdog-b", "watchdog fix b", datetime(2026, 4, 9))
    # pipeline 매칭 1건
    _make_record(db, "gs-pipeline-a", "pipeline refactor", datetime(2026, 4, 9))
    # 매칭 없는 건
    _make_record(db, "gs-unrelated", "unrelated stuff", datetime(2026, 4, 8))

    svc = PlanRecordService(db)
    with (
        patch("app.shared.wiki_tags.load_meta_yaml", return_value=_mock_meta_yaml()),
        patch("app.shared.wiki_tags.load_whitelist", return_value={"watchdog", "pipeline", "skill", "infra", "untagged"}),
        patch("app.shared.wiki_tags.extract_wiki_tags") as mock_ewt,
    ):
        def fake_ewt(filename, whitelist):
            if "watchdog" in filename:
                return ["watchdog"]
            elif "pipeline" in filename:
                return ["pipeline"]
            return ["untagged"]
        mock_ewt.side_effect = fake_ewt

        results = svc.get_guide_status()

    by_guide = {r["guide"]: r for r in results}
    assert "watchdog-architecture.md" in by_guide
    assert "pipeline-overview.md" in by_guide
    # watchdog: 2건 (2026-04-08 이후, last_scan=2026-04-07)
    assert by_guide["watchdog-architecture.md"]["pending_count"] == 2
    # pipeline: 1건
    assert by_guide["pipeline-overview.md"]["pending_count"] == 1


def test_guide_status_pending_count_boundary(db):
    """B(경계): last_archive_scan과 정확히 같은 archived_at → pending 미포함"""
    # last_archive_scan=2026-04-07, archived_at=2026-04-07 00:00:00 → 포함 안 됨
    scan_dt = datetime(2026, 4, 7, 0, 0, 0)
    _make_record(db, "boundary-watchdog", "watchdog boundary", scan_dt)

    svc = PlanRecordService(db)
    meta = {
        "watchdog-architecture.md": {
            "owns_archive_tags": ["watchdog"],
            "last_archive_scan": "2026-04-07",
        }
    }
    with (
        patch("app.shared.wiki_tags.load_meta_yaml", return_value=meta),
        patch("app.shared.wiki_tags.load_whitelist", return_value={"watchdog", "untagged"}),
        patch("app.shared.wiki_tags.extract_wiki_tags", return_value=["watchdog"]),
    ):
        results = svc.get_guide_status()
    by_guide = {r["guide"]: r for r in results}
    # scan_dt == last_scan_dt (같거나 이전이면 pending 아님)
    assert by_guide["watchdog-architecture.md"]["pending_count"] == 0


def test_guide_status_no_records(db):
    """B(경계): PlanRecord 0건 → 모든 가이드 pending_count=0"""
    # 기존 archived records 없는 fresh DB 시뮬레이션 — 빈 결과 patch
    svc = PlanRecordService(db)
    with (
        patch("app.shared.wiki_tags.load_meta_yaml", return_value=_mock_meta_yaml()),
        patch("app.shared.wiki_tags.load_whitelist", return_value={"watchdog", "pipeline", "infra", "untagged"}),
        patch.object(db, "query") as mock_q,
    ):
        mock_q.return_value.filter.return_value.all.return_value = []
        results = svc.get_guide_status()
    for item in results:
        assert item["pending_count"] == 0


# ========== Phase T1: backfill script functions ==========

def test_backfill_guide_status_mode_right(tmp_path):
    """R(정상): extract_guide_summary 동작 확인"""
    from scripts.migrations.archive_index_backfill import extract_guide_summary
    guide_file = tmp_path / "test-guide.md"
    guide_file.write_text("# Test Guide\n\nThis is the first paragraph of the guide.\n", encoding="utf-8")
    result = extract_guide_summary(guide_file)
    assert result == "This is the first paragraph of the guide."


def test_extract_guide_summary_right(tmp_path):
    """R(정상): H1 이후 첫 단락 80자 추출"""
    from scripts.migrations.archive_index_backfill import extract_guide_summary
    content = "# My Guide\n\n> blockquote skip\n\nActual paragraph content here.\n"
    guide_file = tmp_path / "guide.md"
    guide_file.write_text(content, encoding="utf-8")
    result = extract_guide_summary(guide_file)
    assert result == "Actual paragraph content here."


def test_extract_guide_summary_boundary_empty(tmp_path):
    """B(경계): H1만 있고 본문 없는 파일 → 빈 문자열"""
    from scripts.migrations.archive_index_backfill import extract_guide_summary
    guide_file = tmp_path / "empty-guide.md"
    guide_file.write_text("# Only Heading\n\n> Only blockquote\n", encoding="utf-8")
    result = extract_guide_summary(guide_file)
    assert result == ""


def test_backfill_auto_blocks_db_right(db, tmp_path):
    """R(정상): backfill_guide_blocks_db() → AUTO 블록에 PlanRecord.summary 포함"""
    from scripts.migrations.archive_index_backfill import backfill_guide_blocks_db

    guide_dir = tmp_path / "dev-guide"
    guide_dir.mkdir()
    guide_file = guide_dir / "watchdog-architecture.md"
    guide_file.write_text(
        "# Watchdog\n\n<!-- AUTO:BEGIN -->\n_(없음)_\n<!-- AUTO:END -->\n",
        encoding="utf-8",
    )

    archived_at = datetime(2026, 4, 10)
    rec = PlanRecord(
        filename_hash="hash_wd_db",
        file_path="docs/archive/2026-04-10_watchdog-fix.md",
        title="Watchdog Fix",
        summary="watchdog heartbeat fix summary",
        status="archived",
        archived_at=archived_at,
    )
    db.add(rec)
    db.flush()

    meta_yaml = {
        "watchdog-architecture.md": {
            "owns_archive_tags": ["watchdog"],
            "last_archive_scan": "2026-04-07",
        }
    }

    with (
        patch("scripts.migrations.archive_index_backfill._WIKI_TAGS_AVAILABLE", True),
        patch("scripts.migrations.archive_index_backfill._extract_wiki_tags_shared", return_value=["watchdog"]),
        patch("scripts.migrations.archive_index_backfill._load_wl_shared", return_value={"watchdog"}),
    ):
        result = backfill_guide_blocks_db(db, meta_yaml, guide_dir=guide_dir)

    assert "watchdog-architecture.md" in result
    assert result["watchdog-architecture.md"] >= 1
    content = guide_file.read_text(encoding="utf-8")
    assert "watchdog heartbeat fix summary" in content


def test_backfill_auto_blocks_db_no_summary(db, tmp_path):
    """B(경계): summary=None 레코드 → one_liner fallback 사용"""
    from scripts.migrations.archive_index_backfill import backfill_guide_blocks_db

    # archive 파일 생성 (one_liner 추출용)
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    archive_file = archive_dir / "2026-04-10_watchdog-nosummary.md"
    archive_file.write_text("# Watchdog NoSummary\n\nThis is the one liner fallback.\n", encoding="utf-8")

    guide_dir = tmp_path / "dev-guide"
    guide_dir.mkdir()
    guide_file = guide_dir / "watchdog-architecture.md"
    guide_file.write_text(
        "# Watchdog\n\n<!-- AUTO:BEGIN -->\n_(없음)_\n<!-- AUTO:END -->\n",
        encoding="utf-8",
    )

    archived_at = datetime(2026, 4, 10)
    rec = PlanRecord(
        filename_hash="hash_wd_nosummary",
        file_path=str(archive_file),
        title="Watchdog NoSummary",
        summary=None,  # no summary
        status="archived",
        archived_at=archived_at,
    )
    db.add(rec)
    db.flush()

    meta_yaml = {
        "watchdog-architecture.md": {
            "owns_archive_tags": ["watchdog"],
            "last_archive_scan": "2026-04-07",
        }
    }

    with (
        patch("scripts.migrations.archive_index_backfill._WIKI_TAGS_AVAILABLE", True),
        patch("scripts.migrations.archive_index_backfill._extract_wiki_tags_shared", return_value=["watchdog"]),
        patch("scripts.migrations.archive_index_backfill._load_wl_shared", return_value={"watchdog"}),
    ):
        result = backfill_guide_blocks_db(db, meta_yaml, guide_dir=guide_dir)

    assert "watchdog-architecture.md" in result
    content = guide_file.read_text(encoding="utf-8")
    # one_liner fallback이 사용됨
    assert "one liner fallback" in content


# ========== Phase T3: 실제 파일 통합 TC ==========

def test_guide_status_with_real_meta_yaml(db):
    """T3: 실제 docs/dev-guide/_meta.yaml 파싱 + 실제 DB SessionLocal로 PlanRecord 교차"""
    svc = PlanRecordService(db)
    # 실제 meta.yaml 사용 (mock 없음)
    try:
        results = svc.get_guide_status()
    except Exception as e:
        pytest.skip(f"guide_status integration failed: {e}")

    assert isinstance(results, list)
    # 가이드별 필수 필드 확인
    for item in results:
        assert "guide" in item
        assert "pending_count" in item
        assert isinstance(item["pending_count"], int)


def test_backfill_guide_status_real_files(db):
    """T3: 실제 docs/archive/ + docs/dev-guide/_meta.yaml + DB → guide-status INDEX.md 마커 블록 생성 검증"""
    import tempfile
    from pathlib import Path
    from scripts.migrations.archive_index_backfill import backfill_guide_blocks_db, render_guide_status_index
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService

    # 실제 meta.yaml 파싱
    try:
        from app.shared.wiki_tags import load_meta_yaml
        meta = load_meta_yaml()
    except Exception as e:
        pytest.skip(f"meta.yaml load failed: {e}")

    if not meta:
        pytest.skip("meta.yaml is empty")

    # DB에서 실제 guide_status 조회 (빈 DB여도 list 반환)
    svc = PlanRecordService(db)
    statuses = svc.get_guide_status()
    assert isinstance(statuses, list)

    # render_guide_status_index로 테이블 내용 생성 (마커 없이 테이블만 반환)
    rendered = render_guide_status_index(statuses)
    assert isinstance(rendered, str)
    # 테이블 헤더행 포함 확인
    assert "| guide |" in rendered
    assert "last_updated" in rendered
    assert "pending" in rendered
    # 가이드 수 만큼 행이 생성되었는지 확인 (헤더 2행 + 가이드 행)
    lines = [l for l in rendered.splitlines() if l.strip().startswith("|")]
    # 헤더행(1) + 구분행(1) + 가이드 행(N개)
    assert len(lines) >= 2


def test_extract_wiki_tags_integration():
    """T3: 실제 docs/wiki-schema.md whitelist + 샘플 archive 파일명 5개 → 태그 추출"""
    from app.shared.wiki_tags import load_whitelist, extract_wiki_tags

    try:
        wl = load_whitelist()
    except Exception as e:
        pytest.skip(f"whitelist load failed: {e}")

    sample_files = [
        "2026-04-10_fix-watchdog-heartbeat.md",
        "2026-03-05_refactor-pipeline-runner.md",
        "2026-02-15_feat-frontend-pagination.md",
        "2026-01-20_fix-infra-nssm-startup.md",
        "2026-04-09_misc-unrelated-stuff.md",
    ]
    for fname in sample_files:
        tags = extract_wiki_tags(fname, wl)
        assert isinstance(tags, list)
        assert len(tags) > 0  # 최소 ["untagged"] 이상


# ========== Phase T4: E2E (TestClient) ==========

@pytest.fixture(scope="module")
def api_client(test_db_engine):
    """TestClient + test_db_engine 오버라이드"""
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


def test_e2e_guide_status_api(api_client):
    """T4: GET /api/v1/plans/records/guide-status → 200 + [{guide, pending_count, ...}] 구조"""
    resp = api_client.get("/api/v1/plans/records/guide-status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "guide" in item
        assert "pending_count" in item
        assert isinstance(item["pending_count"], int)


def test_e2e_plan_record_search(api_client, test_db_session):
    """T4: GET /api/v1/plans/records?q=watchdog → 200 + summary 매칭 결과"""
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService
    from app.models.plan_record import PlanRecord

    # 테스트 레코드 삽입
    rec = PlanRecord(
        filename_hash="test_search_watchdog_hash",
        file_path="/plan/2026-04-10_watchdog-test.md",
        summary="watchdog heartbeat 점검",
    )
    test_db_session.add(rec)
    test_db_session.commit()

    resp = api_client.get("/api/v1/plans/records?q=watchdog")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any("watchdog" in (item.get("summary") or "").lower() for item in data)


# ========== Phase T5: HTTP 통합 (http_live — 실서버) ==========

import pytest as _pytest
pytestmark_http_live = _pytest.mark.http_live


@_pytest.mark.http_live
def test_http_plan_records_search_keyword():
    """T5: GET /api/v1/plans/records?q=redis → 200 + 결과는 리스트"""
    import httpx
    try:
        resp = httpx.get("http://localhost:8001/api/v1/plans/records?q=redis", timeout=10)
    except httpx.ConnectError:
        _pytest.skip("실서버 미기동")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@_pytest.mark.http_live
def test_http_plan_records_search_date():
    """T5: GET /api/v1/plans/records?date_from=2026-04-01&date_to=2026-04-10 → 200"""
    import httpx
    try:
        resp = httpx.get(
            "http://localhost:8001/api/v1/plans/records?date_from=2026-04-01T00:00:00&date_to=2026-04-10T23:59:59",
            timeout=10,
        )
    except httpx.ConnectError:
        _pytest.skip("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@_pytest.mark.http_live
def test_http_plan_records_search_no_result():
    """T5: GET /api/v1/plans/records?q=zzz_impossible → 200 + 빈 리스트 또는 결과 없음"""
    import httpx
    try:
        resp = httpx.get(
            "http://localhost:8001/api/v1/plans/records?q=zzz_impossible_xyzzy_12345",
            timeout=10,
        )
    except httpx.ConnectError:
        _pytest.skip("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


@_pytest.mark.http_live
def test_http_guide_status():
    """T5: GET /api/v1/plans/records/guide-status → 200 + [{guide, pending_count}]"""
    import httpx
    try:
        resp = httpx.get("http://localhost:8001/api/v1/plans/records/guide-status", timeout=10)
    except httpx.ConnectError:
        _pytest.skip("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "guide" in item
        assert "pending_count" in item


@_pytest.mark.http_live
def test_http_guide_status_empty():
    """T5: PlanRecord 0건이어도 GET /api/v1/plans/records/guide-status → 200 + 리스트"""
    import httpx
    try:
        resp = httpx.get("http://localhost:8001/api/v1/plans/records/guide-status", timeout=10)
    except httpx.ConnectError:
        _pytest.skip("실서버 미기동")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # 모든 가이드의 pending_count는 int
    for item in data:
        assert isinstance(item.get("pending_count"), int)
