"""
단위 TC: plan_archive_listener.py _build_prompt + _handle_archived_sync

DB-first 원칙 + 빈 내용 skip 가드 + filename_only 버그 수정 검증
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
from app.worker.plan_archive_listener import PlanArchiveListener


@pytest.fixture
def listener():
    return PlanArchiveListener()


@pytest.fixture
def memory_db():
    """In-memory SQLite DB with schema created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@contextmanager
def _make_session_local(session):
    """SessionLocal을 in-memory session으로 대체하는 context manager factory."""
    @contextmanager
    def _factory():
        yield session
    return _factory()


# ─── _build_prompt 단위 TC ───────────────────────────────────────────────────

def test_build_prompt_uses_file_content_when_provided(listener):
    """R: file_content 파라미터가 있으면 파일 읽기 없이 해당 내용을 프롬프트에 포함한다."""
    content = "# 테스트 계획서\n이 내용이 프롬프트에 들어가야 한다."
    filename = "/some/archive/path/2026-01-01_test-plan.md"

    with patch("app.worker.plan_archive_listener.Path") as mock_path_cls:
        # Path 자체를 mock하지 않고, 파일 읽기가 호출되지 않는지 확인
        with patch("app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt") as mock_build:
            mock_build.return_value = "mocked_prompt"
            result = listener._build_prompt(filename, file_content=content)

    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args[1]
    assert call_kwargs["file_content"] == content
    assert call_kwargs["filename"] == "2026-01-01_test-plan.md"  # 파일명만


def test_build_prompt_falls_back_to_file_when_file_content_empty(listener, tmp_path):
    """R: file_content가 비어 있고 파일이 존재하면 파일 내용을 읽어 프롬프트에 포함한다."""
    plan_file = tmp_path / "2026-01-02_my-plan.md"
    plan_file.write_text("# 파일에서 읽은 내용", encoding="utf-8")

    with patch("app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt") as mock_build:
        mock_build.return_value = "prompt_from_file"
        result = listener._build_prompt(str(plan_file), file_content="")

    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args[1]
    assert "파일에서 읽은 내용" in call_kwargs["file_content"]
    assert call_kwargs["filename"] == "2026-01-02_my-plan.md"


def test_build_prompt_filename_only_on_file_read_error(listener):
    """E: 파일 읽기 예외 시 filename_only = Path(filename).name 적용 — 풀패스 노출 없음."""
    filename = "/long/path/to/archive/2026-01-03_bugfix.md"

    with patch("app.modules.claude_worker.services.plan_analyze_handler.build_plan_analyze_prompt") as mock_build:
        mock_build.return_value = "error_prompt"
        result = listener._build_prompt(filename, file_content="")

    # 파일이 없으면 read_text가 FileNotFoundError를 발생시킴 → except 브랜치
    mock_build.assert_called_once()
    call_kwargs = mock_build.call_args[1]
    # filename_only는 반드시 파일명만이어야 함 (풀패스 금지)
    assert call_kwargs["filename"] == "2026-01-03_bugfix.md"
    assert "/" not in call_kwargs["filename"]
    assert "\\" not in call_kwargs["filename"]


# ─── _handle_archived_sync 단위 TC ───────────────────────────────────────────

def _make_db_factory(session):
    """SessionLocal context manager를 특정 session으로 대체."""
    @contextmanager
    def _factory():
        yield session
    return _factory


def test_handle_archived_sync_skips_llm_request_when_content_empty(memory_db, listener):
    """E: raw_content=None이고 파일도 없으면 LLMRequest가 생성되지 않는다."""
    filename = "/nonexistent/path/2026-01-04_plan.md"

    # PlanRecord 미리 삽입 (raw_content = None) — 올바른 hash 사용
    record = PlanRecord(
        filename_hash=_compute_filename_hash(filename),
        file_path=filename,
        raw_content=None,
    )
    memory_db.add(record)
    memory_db.commit()

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_db_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            listener._handle_archived_sync(filename)

    # LLMRequest가 생성되지 않아야 함
    count = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").count()
    assert count == 0


def test_handle_archived_sync_saves_file_content_to_raw_content(memory_db, listener, tmp_path):
    """R: 파일 읽기 성공 시 record.raw_content가 DB에 저장된다."""
    plan_file = tmp_path / "2026-01-05_feature.md"
    plan_file.write_text("# 피처 계획서\n내용 있음", encoding="utf-8")

    record = PlanRecord(
        filename_hash=_compute_filename_hash(str(plan_file)),
        file_path=str(plan_file),
        raw_content=None,
    )
    memory_db.add(record)
    memory_db.commit()

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_db_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            with patch("app.worker.plan_archive_listener.LLMService") as mock_llm_svc:
                mock_llm_svc.return_value.resolve_provider_model.return_value = ("claude", "test-model")
                listener._handle_archived_sync(str(plan_file))

    memory_db.refresh(record)
    assert record.raw_content is not None
    assert "피처 계획서" in record.raw_content


def test_handle_archived_sync_uses_raw_content_when_available(memory_db, listener):
    """R: raw_content가 있으면 파일 읽기 없이 raw_content로 LLMRequest를 생성한다."""
    filename = "/archive/2026-01-06_existing-content.md"
    raw = "# DB에 저장된 내용\n파일 없어도 OK"

    record = PlanRecord(
        filename_hash=_compute_filename_hash(filename),
        file_path=filename,
        raw_content=raw,
    )
    memory_db.add(record)
    memory_db.commit()

    file_read_called = []

    original_path_cls = Path

    def tracking_path(arg):
        p = original_path_cls(arg)
        orig_read = p.read_text

        def tracked_read(**kwargs):
            file_read_called.append(arg)
            return orig_read(**kwargs)

        p.read_text = tracked_read
        return p

    with patch("app.worker.plan_archive_listener.SessionLocal", _make_db_factory(memory_db)):
        with patch("app.worker.plan_archive_listener.get_git_first_commit_date", return_value=None):
            with patch("app.worker.plan_archive_listener.LLMService") as mock_llm_svc:
                mock_llm_svc.return_value.resolve_provider_model.return_value = ("claude", "test-model")
                listener._handle_archived_sync(filename)

    # 파일이 없어도 LLMRequest가 생성됐는지 확인
    req = memory_db.query(LLMRequest).filter_by(caller_type="plan_archive_analyze").first()
    assert req is not None
    assert "DB에 저장된 내용" in req.prompt
