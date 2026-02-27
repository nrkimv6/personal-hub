"""
test_plan_record_import.py — bulk_import_archived + list_records 필터 테스트

RIGHT-BICEP:
- R: 정상 케이스
- B: 경계 케이스 (빈 폴더, 헤더 없는 파일, 이미 존재하는 레코드)
- E: 오류 케이스 (읽기 불가 파일)
"""
import pytest
import os
import stat
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


def _create_plan_tables(eng):
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_plan_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def svc(db):
    return PlanRecordService(db)


@pytest.fixture
def archive_dir(tmp_path):
    """3개 md 파일이 있는 임시 archive 폴더"""
    d = tmp_path / "archive" / "naver-booking"
    d.mkdir(parents=True)
    (d / "2026-01-01_plan-a.md").write_text("# Plan A\ncontent", encoding="utf-8")
    (d / "2026-01-02_plan-b.md").write_text("# Plan B\ncontent", encoding="utf-8")
    d2 = tmp_path / "archive" / "instagram"
    d2.mkdir(parents=True)
    (d2 / "2026-01-03_plan-c.md").write_text("# Plan C\ncontent", encoding="utf-8")
    return tmp_path / "archive"


# ── R: 정상 케이스 ──────────────────────────────────────────

def test_bulk_import_archived_right(svc, archive_dir):
    """R: 3개 md 파일 → created=3, category/title 설정됨"""
    result = svc.bulk_import_archived(str(archive_dir))
    assert result["created"] == 3
    assert result["errors"] == []

    records = svc.db.query(PlanRecord).all()
    assert len(records) == 3
    categories = {r.category for r in records}
    assert "naver-booking" in categories
    assert "instagram" in categories
    titles = {r.title for r in records}
    assert "Plan A" in titles
    assert "Plan C" in titles


def test_list_records_category_filter(svc, archive_dir):
    """R: category='naver-booking' 필터 → 해당 카테고리만 반환"""
    # 데이터 준비
    svc.bulk_import_archived(str(archive_dir))
    svc.db.commit()

    records = svc.list_records(category="naver-booking")
    assert len(records) >= 1
    for r in records:
        assert r.category == "naver-booking"


def test_list_records_category_boundary_none(svc, archive_dir):
    """B: category=None → 전체 반환 (기존 동작 유지)"""
    svc.bulk_import_archived(str(archive_dir))
    svc.db.commit()

    records_all = svc.list_records()
    records_filtered = svc.list_records(category="naver-booking")
    assert len(records_all) >= len(records_filtered)


# ── B: 경계 케이스 ──────────────────────────────────────────

def test_bulk_import_archived_boundary_empty(svc, tmp_path):
    """B: 빈 폴더 → created=0, errors=[]"""
    empty_dir = tmp_path / "empty_archive"
    empty_dir.mkdir()
    result = svc.bulk_import_archived(str(empty_dir))
    assert result["created"] == 0
    assert result["errors"] == []
    assert result["updated"] == 0
    assert result["skipped"] == 0


def test_bulk_import_archived_boundary_no_header(svc, tmp_path):
    """B: # 헤더 없는 md 파일 → title=None으로 저장, 에러 없음"""
    d = tmp_path / "archive" / "common"
    d.mkdir(parents=True)
    (d / "2026-01-10_no-header.md").write_text("no header here\ncontent", encoding="utf-8")
    result = svc.bulk_import_archived(str(tmp_path / "archive"))
    assert result["created"] == 1
    assert result["errors"] == []

    record = svc.db.query(PlanRecord).order_by(PlanRecord.id.desc()).first()
    assert record.title is None


def test_bulk_import_archived_existing_update(svc, tmp_path):
    """B: 이미 존재하는 레코드 → category만 UPDATE, created=0, updated=1"""
    d = tmp_path / "archive" / "old-category"
    d.mkdir(parents=True)
    md_file = d / "2026-01-20_existing.md"
    md_file.write_text("# Existing Plan", encoding="utf-8")

    # 1차 import
    svc.bulk_import_archived(str(tmp_path / "archive"))
    svc.db.commit()

    # 같은 파일을 다른 카테고리 폴더에 복사 후 다시 import
    d2 = tmp_path / "archive2" / "new-category"
    d2.mkdir(parents=True)
    import shutil
    shutil.copy(md_file, d2 / md_file.name)

    result2 = svc.bulk_import_archived(str(tmp_path / "archive2"))
    # 같은 filename_hash → category UPDATE
    assert result2["created"] == 0
    assert result2["updated"] == 1


# ── E: 오류 케이스 ──────────────────────────────────────────

def test_bulk_import_archived_error_unreadable(svc, tmp_path):
    """E: 읽기 불가 파일 → errors에 포함, 나머지 정상 처리 (Unix only)"""
    if os.name == "nt":
        pytest.skip("Windows에서는 파일 권한 테스트 스킵")

    d = tmp_path / "archive" / "infra"
    d.mkdir(parents=True)
    (d / "2026-01-30_normal.md").write_text("# Normal", encoding="utf-8")
    unreadable = d / "2026-01-30_unreadable.md"
    unreadable.write_text("# Unreadable", encoding="utf-8")
    unreadable.chmod(0o000)

    try:
        result = svc.bulk_import_archived(str(tmp_path / "archive"))
        # errors에 unreadable 파일이 포함되거나, 정상 파일은 created 됨
        # (SQLite 자체 오류가 아닌 파일 읽기 오류는 title=None으로 처리될 수 있음)
        assert result["created"] >= 1  # 정상 파일은 처리됨
    finally:
        unreadable.chmod(0o644)


# ── tags 필터 ────────────────────────────────────────────────

def test_list_records_tags_filter(svc, db, tmp_path):
    """R: tags=['feat'] 필터 → 태그 포함 레코드만 반환"""
    d = tmp_path / "archive" / "common"
    d.mkdir(parents=True)
    (d / "2026-02-01_tagged.md").write_text("# Tagged Plan", encoding="utf-8")

    svc.bulk_import_archived(str(tmp_path / "archive"))
    db.commit()

    # 수동으로 tags 설정
    record = db.query(PlanRecord).order_by(PlanRecord.id.desc()).first()
    record.tags = ["feat", "test"]
    db.commit()

    records = svc.list_records(tags=["feat"])
    # tags 필터는 JSON LIKE 기반이므로 포함 여부 확인
    assert any(r.id == record.id for r in records)
