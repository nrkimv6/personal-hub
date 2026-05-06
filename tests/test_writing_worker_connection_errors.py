"""tests/test_writing_worker_connection_errors.py

WritingWorker / TopicExtractWorker connection error 전파 계약 단위 TC (Phase T1)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    import psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

pytestmark = pytest.mark.skipif(not _HAS_PSYCOPG2, reason="psycopg2 없음")


def _make_pg_connection_error() -> Exception:
    return psycopg2.OperationalError("connection refused to server")


def _make_writing_worker(mock_db):
    """WritingWorker를 외부 의존성 없이 생성."""
    with (
        patch("app.modules.writing.worker.writing_worker.LLMService"),
        patch("app.modules.writing.worker.writing_worker.ElementSelector"),
    ):
        from app.modules.writing.worker.writing_worker import WritingWorker
        return WritingWorker(mock_db, project_root=Path("/tmp"))


def _make_topic_worker(mock_db):
    """TopicExtractWorker를 외부 의존성 없이 생성."""
    with patch("app.modules.writing.worker.topic_extract_worker.LLMService"):
        from app.modules.writing.worker.topic_extract_worker import TopicExtractWorker
        return TopicExtractWorker(mock_db)


# ---------------------------------------------------------------------------
# T1-01: WritingWorker.run() connection error 즉시 전파
# ---------------------------------------------------------------------------

def test_writing_worker_run_reraises_connection_error_right():
    """R: WritingWorker.run() — DB connection error는 local traceback 없이 즉시 raise."""
    mock_db = MagicMock()
    mock_db.query.return_value.count.side_effect = _make_pg_connection_error()

    worker = _make_writing_worker(mock_db)

    mock_schedule = MagicMock()
    mock_schedule.get_target_config.return_value = {}
    mock_schedule.target_config = {}
    mock_run = MagicMock()

    with patch("app.modules.writing.worker.writing_worker.logger") as mock_logger:
        with pytest.raises(psycopg2.OperationalError):
            worker.run(mock_schedule, mock_run)

        # connection error 경로에서 logger.error(exc_info=True) 호출 금지
        for call in mock_logger.error.call_args_list:
            kw = call[1] if len(call) > 1 else {}
            assert not kw.get("exc_info"), "connection error 경로에서 exc_info=True 로그 금지"

    # mark_failed가 호출되지 않아야 한다 (connection error 즉시 raise)
    mock_run.mark_failed.assert_not_called()


# ---------------------------------------------------------------------------
# T1-02: _queue_mix_writing() connection error → False 아닌 예외 전파
# ---------------------------------------------------------------------------

def test_queue_mix_writing_reraises_connection_error_error():
    """R: _queue_mix_writing() — DB connection error는 False 반환 대신 예외 전파."""
    mock_db = MagicMock()
    mock_db.commit.side_effect = _make_pg_connection_error()

    mock_selector = MagicMock()
    mock_selector.select_sources.return_value = [
        MagicMock(id=i, content=f"content {i}") for i in range(3)
    ]

    with (
        patch("app.modules.writing.worker.writing_worker.LLMService") as mock_llm_cls,
        patch("app.modules.writing.worker.writing_worker.ElementSelector", return_value=mock_selector),
    ):
        mock_llm_svc = MagicMock()
        mock_llm_svc.resolve_provider_model.return_value = ("openai", "gpt-4o")
        mock_llm_cls.return_value = mock_llm_svc

        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext
        worker = WritingWorker(mock_db, project_root=Path("/tmp"))

    slot_context = SlotContext()

    with pytest.raises(psycopg2.OperationalError):
        worker._queue_mix_writing(1, slot_context)

    # rollback은 호출되어야 한다
    mock_db.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# T1-03: TopicExtractWorker.run() connection error 즉시 전파
# ---------------------------------------------------------------------------

def test_topic_extract_worker_run_reraises_connection_error_right():
    """R: TopicExtractWorker.run() — DB connection error는 local traceback 없이 즉시 raise."""
    mock_db = MagicMock()
    # _get_unprocessed_sources() 내부 query 에서 connection error
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = \
        _make_pg_connection_error()

    worker = _make_topic_worker(mock_db)

    mock_schedule = MagicMock()
    mock_run = MagicMock()

    with patch("app.modules.writing.worker.topic_extract_worker.logger") as mock_logger:
        with pytest.raises(psycopg2.OperationalError):
            worker.run(mock_schedule, mock_run)

        for call in mock_logger.error.call_args_list:
            kw = call[1] if len(call) > 1 else {}
            assert not kw.get("exc_info"), "connection error 경로에서 exc_info=True 로그 금지"

    mock_run.mark_failed.assert_not_called()


# ---------------------------------------------------------------------------
# T1-E: non-connection error는 기존 동작 유지
# ---------------------------------------------------------------------------

def test_writing_worker_run_keeps_traceback_for_non_connection_error():
    """E: WritingWorker.run() — DB 아닌 일반 예외는 기존 logger.error + mark_failed 유지."""
    mock_db = MagicMock()
    mock_db.query.return_value.count.side_effect = ValueError("unexpected error")

    worker = _make_writing_worker(mock_db)

    mock_schedule = MagicMock()
    mock_schedule.get_target_config.return_value = {}
    mock_schedule.target_config = {}
    mock_run = MagicMock()

    with patch("app.modules.writing.worker.writing_worker.logger") as mock_logger:
        with pytest.raises(ValueError):
            worker.run(mock_schedule, mock_run)

        # non-connection error는 logger.error 호출 필수
        assert mock_logger.error.called, "non-connection error는 logger.error 호출 필수"

    mock_run.mark_failed.assert_called_once()


def test_queue_mix_writing_returns_false_for_non_connection_error():
    """E: _queue_mix_writing() — non-connection error는 False 반환 유지 (traceback 후)."""
    mock_db = MagicMock()
    mock_db.commit.side_effect = ValueError("unexpected non-pg error")

    mock_selector = MagicMock()
    mock_selector.select_sources.return_value = [
        MagicMock(id=i, content=f"content {i}") for i in range(3)
    ]

    with (
        patch("app.modules.writing.worker.writing_worker.LLMService") as mock_llm_cls,
        patch("app.modules.writing.worker.writing_worker.ElementSelector", return_value=mock_selector),
    ):
        mock_llm_svc = MagicMock()
        mock_llm_svc.resolve_provider_model.return_value = ("openai", "gpt-4o")
        mock_llm_cls.return_value = mock_llm_svc

        from app.modules.writing.worker.writing_worker import WritingWorker, SlotContext
        worker = WritingWorker(mock_db, project_root=Path("/tmp"))

    slot_context = SlotContext()
    result = worker._queue_mix_writing(1, slot_context)

    assert result is False, "non-connection error는 False 반환 유지"
