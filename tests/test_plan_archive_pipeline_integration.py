"""
T3: plan-archive DB-first 통합 TC

실제 DB(in-memory SQLite) + 실물 파일시스템 사용.
mock 최소화 — SessionLocal만 in-memory로 대체.
"""

import pytest
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.worker.plan_archive_listener import PlanArchiveListener


@pytest.fixture
def memory_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def memory_db(memory_engine):
    Session = sessionmaker(bind=memory_engine)
    session = Session()
    yield session
    session.close()


def _make_session_factory(session):
    @contextmanager
    def _factory():
        yield session
    return _factory


@pytest.fixture
def listener():
    return PlanArchiveListener()


def _insert_record(session, file_path, raw_content=None):
    import hashlib
    filename_hash = hashlib.sha256(Path(file_path).name.encode()).hexdigest()
    record = PlanRecord(
        filename_hash=filename_hash,
        file_path=file_path,
        raw_content=raw_content,
        archived_at=datetime(2026, 1, 1),
        llm_processed_at=None,
    )
    session.add(record)
    session.commit()
    return record


# ─── T3: DB raw_content 활용 통합 TC ─────────────────────────────────────────

def test_handle_archived_sync_uses_db_raw_content(memory_db, listener):
    """T3-1: PlanRecord에 raw_content 설정 후 존재하지 않는 경로로 호출
    → LLMRequest.prompt에 raw_content가 포함됨 (파일 mock 없음).
    """
    raw = "# DB 원본 계획서\n파일이 없어도 이 내용이 분석된다"
    filename = "/archive/gone/2026-03-01_integration-test.md"

    _insert_record(memory_db, filename, raw_content=raw)

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_session_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            with patch("app.worker.plan_archive_listener.LLMService") as mock_llm:
                mock_llm.return_value.resolve_provider_model.return_value = ("claude", "test-model")
                listener._handle_archived_sync(filename)

    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is not None, "LLMRequest가 생성되어야 한다"
    assert "DB 원본 계획서" in req.prompt, "prompt에 raw_content가 포함되어야 한다"
    assert "파일이 없어도" in req.prompt


def test_handle_archived_sync_creates_request_with_file_content(memory_db, listener, tmp_path):
    """T3-2: raw_content=None, 실제 파일 존재 → LLMRequest 생성 + prompt에 파일 내용 포함."""
    plan_file = tmp_path / "2026-03-02_real-file-test.md"
    plan_file.write_text("# 실제 파일 내용\n통합 테스트 검증용", encoding="utf-8")

    _insert_record(memory_db, str(plan_file), raw_content=None)

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_session_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            with patch("app.worker.plan_archive_listener.LLMService") as mock_llm:
                mock_llm.return_value.resolve_provider_model.return_value = ("claude", "test-model")
                listener._handle_archived_sync(str(plan_file))

    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is not None, "LLMRequest가 생성되어야 한다"
    assert "실제 파일 내용" in req.prompt

    # raw_content도 DB에 저장됐는지 확인
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
    filename_hash = _compute_filename_hash(str(plan_file))
    record = memory_db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
    assert record is not None
    assert record.raw_content is not None
    assert "실제 파일 내용" in record.raw_content


def test_handle_archived_sync_skips_when_both_fail(memory_db, listener):
    """T3-3: raw_content=None, 파일 없음 → LLMRequest 미생성 + llm_processed_at=None 유지.

    _process_unprocessed_plans의 재처리 대상에 남아 있음을 검증.
    """
    filename = "/totally/missing/2026-03-03_no-content.md"
    record = _insert_record(memory_db, filename, raw_content=None)

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_session_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            listener._handle_archived_sync(filename)

    # LLMRequest 미생성 확인
    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is None, "빈 내용이면 LLMRequest가 생성되지 않아야 한다"

    # llm_processed_at = None 유지 — 재처리 대상으로 남아야 함
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
    filename_hash = _compute_filename_hash(filename)
    updated = memory_db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
    assert updated.llm_processed_at is None, "llm_processed_at이 None이어야 재처리 대상이다"
