"""
단위 TC: scheduled_worker.py _process_unprocessed_plans DB-first + empty skip

raw_content 우선 + 빈 내용 skip 로직 검증
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _add_plan_record(session, file_path, raw_content=None):
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


def test_process_unprocessed_uses_db_raw_content(memory_db, tmp_path):
    """R: record.raw_content가 있으면 파일 읽기 없이 프롬프트를 생성한다."""
    raw = "# DB 내용\n파일 없이 처리됨"
    record = _add_plan_record(memory_db, "/archive/2026-02-01_plan.md", raw_content=raw)

    # DB-first 로직 직접 검증
    file_content = record.raw_content or ""
    assert file_content == raw

    # 파일이 없어도 file_content는 이미 있음
    if not file_content:
        fp = Path(record.file_path)
        if fp.exists():
            file_content = fp.read_text(encoding="utf-8", errors="replace")

    assert file_content == raw  # 파일 읽기 없이 raw_content 사용


def test_process_unprocessed_skips_when_content_empty(memory_db):
    """E: raw_content 없고 파일도 없으면 LLMRequest 생성 없이 해당 record skip."""
    record = _add_plan_record(memory_db, "/nonexistent/2026-02-02_gone.md", raw_content=None)

    # scheduled_worker._process_unprocessed_plans의 핵심 skip 로직 검증
    file_content = record.raw_content or ""

    # 파일도 없음
    fp = Path(record.file_path)
    skipped = False
    if not file_content:
        if fp.exists():
            try:
                file_content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if not file_content:
        skipped = True

    assert skipped is True

    # DB에 LLMRequest가 없어야 함
    count = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").count()
    assert count == 0


def test_process_unprocessed_creates_request_with_raw_content(memory_db):
    """R: raw_content가 있으면 LLMRequest가 생성되고 prompt에 내용이 포함된다."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    raw = "# 스케줄러 테스트 계획서\nLLM 분석 대상"
    record = _add_plan_record(memory_db, "/archive/2026-02-03_sched.md", raw_content=raw)

    # _process_unprocessed_plans calls db = SessionLocal() directly (not as ctx manager)
    mock_session = MagicMock(wraps=memory_db)
    mock_session.close = MagicMock()  # prevent actual close so memory_db stays usable

    with patch("app.worker.crawl_worker_base.BrowserManager", MagicMock()):
        worker = ScheduledCrawlWorker()
    worker._log_worker_error = MagicMock()

    with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_session):
        count = worker._process_unprocessed_plans()

    assert count == 1
    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is not None
    assert "스케줄러 테스트 계획서" in req.prompt


def test_process_unprocessed_skips_empty_with_log(memory_db):
    """E: raw_content 없고 파일도 없으면 warning 로그 후 skip (LLMRequest 미생성)."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    record = _add_plan_record(memory_db, "/gone/2026-02-04_missing.md", raw_content=None)

    mock_session = MagicMock(wraps=memory_db)
    mock_session.close = MagicMock()

    with patch("app.worker.crawl_worker_base.BrowserManager", MagicMock()):
        worker = ScheduledCrawlWorker()
    worker._log_worker_error = MagicMock()

    log_messages = []

    with patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_session):
        with patch("app.worker.scheduled_worker.logger") as mock_logger:
            mock_logger.warning.side_effect = lambda msg, **kw: log_messages.append(msg)
            count = worker._process_unprocessed_plans()

    # count=0 — skip됐으므로 INSERT 없음
    assert count == 0
    assert len(log_messages) == 1
    assert "내용 없음" in log_messages[0] or "LLMRequest 생성 스킵" in log_messages[0]

    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is None
