"""tests/worker/test_schedule_handler_pg_error.py

Scheduler sync helper의 connection error 전파 계약 단위 TC (Phase T1)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

pytestmark = pytest.mark.skipif(not _HAS_PSYCOPG2, reason="psycopg2 없음")


def _pg_conn_err() -> Exception:
    return psycopg2.OperationalError("connection refused to server")


# ---------------------------------------------------------------------------
# T1-A: WritingTask sync helper
# ---------------------------------------------------------------------------

def test_writing_task_sync_helper_propagates_operationalerror_right():
    """R: _run_writing_job_sync() — connection error는 문자열로 바꾸지 않고 그대로 raise."""
    from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = MagicMock()
    # WritingWorker.run() 진입 전 DB 쿼리에서 connection error
    mock_db.query.return_value.count.side_effect = _pg_conn_err()

    def db_factory():
        return mock_db

    with (
        patch("app.modules.writing.schedulers.writing_task_schedule.WritingWorker") as mock_ww_cls,
    ):
        mock_ww = MagicMock()
        mock_ww.run.side_effect = _pg_conn_err()
        mock_ww_cls.return_value = mock_ww

        with pytest.raises(psycopg2.OperationalError):
            WritingTaskScheduler._run_writing_job_sync(
                schedule_id=1,
                run_id=1,
                db_factory=db_factory,
                worker_name="test",
            )

    # DB가 닫혀야 함
    mock_db.close.assert_called_once()


def test_writing_task_sync_helper_returns_error_dict_for_non_connection_error():
    """E: _run_writing_job_sync() — non-connection error는 {"error": str} 반환 유지."""
    from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler

    mock_db = MagicMock()

    def db_factory():
        return mock_db

    with patch("app.modules.writing.schedulers.writing_task_schedule.WritingWorker") as mock_ww_cls:
        mock_ww = MagicMock()
        mock_ww.run.side_effect = ValueError("non-pg error")
        mock_ww_cls.return_value = mock_ww

        result = WritingTaskScheduler._run_writing_job_sync(
            schedule_id=1,
            run_id=1,
            db_factory=db_factory,
            worker_name="test",
        )

    assert "error" in result
    mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# T1-B: KeywordAnalysis sync helper
# ---------------------------------------------------------------------------

def test_keyword_analysis_sync_helper_propagates_operationalerror_right():
    """R: _run_keyword_job_sync() — connection error는 그대로 raise."""
    from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler

    mock_db = MagicMock()

    def db_factory():
        return mock_db

    with patch(
        "app.modules.writing.schedulers.keyword_analysis_schedule.KeywordAnalysisScheduler"
        "._run_keyword_job_sync.__wrapped__" if False else
        "app.modules.writing.schedulers.keyword_analysis_schedule"
    ):
        pass

    # KeywordAnalyzer 직접 mock
    with patch(
        "app.modules.writing.schedulers.keyword_analysis_schedule"
    ):
        pass

    # 단순하게 KeywordAnalyzer import를 mock
    mock_analyzer = MagicMock()
    mock_analyzer.analyze_incremental.side_effect = _pg_conn_err()

    with patch.dict(
        "sys.modules",
        {"app.modules.writing.services.keyword_analyzer": MagicMock(KeywordAnalyzer=MagicMock(return_value=mock_analyzer))},
    ):
        with pytest.raises(psycopg2.OperationalError):
            KeywordAnalysisScheduler._run_keyword_job_sync(
                config={"mode": "incremental"},
                db_factory=db_factory,
                worker_name="test",
            )

    mock_db.close.assert_called_once()


def test_keyword_analysis_sync_helper_propagates_operationalerror_right_v2():
    """R(v2): KeywordAnalyzer 생성 자체에서 connection error → raise."""
    from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler

    mock_db = MagicMock()

    def db_factory():
        return mock_db

    mock_ka_cls = MagicMock(side_effect=_pg_conn_err())

    with patch.dict(
        "sys.modules",
        {"app.modules.writing.services.keyword_analyzer": MagicMock(KeywordAnalyzer=mock_ka_cls)},
    ):
        with pytest.raises(psycopg2.OperationalError):
            KeywordAnalysisScheduler._run_keyword_job_sync(
                config={},
                db_factory=db_factory,
                worker_name="test",
            )

    mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# T1-C: TopicExtract sync helper
# ---------------------------------------------------------------------------

def test_topic_extract_sync_helper_propagates_operationalerror_right():
    """R: _run_topic_job_sync() — connection error는 그대로 raise."""
    from app.modules.writing.schedulers.topic_extract_schedule import TopicExtractScheduler

    mock_db = MagicMock()
    # schedule/run 쿼리 OK, worker.run()에서 connection error
    mock_schedule = MagicMock()
    mock_run_obj = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.side_effect = [mock_schedule, mock_run_obj]

    def db_factory():
        return mock_db

    with patch(
        "app.modules.writing.schedulers.topic_extract_schedule.TopicExtractWorker"
    ) as mock_tew_cls:
        mock_tew = MagicMock()
        mock_tew.run.side_effect = _pg_conn_err()
        mock_tew_cls.return_value = mock_tew

        with pytest.raises(psycopg2.OperationalError):
            TopicExtractScheduler._run_topic_job_sync(
                schedule_id=1,
                run_id=1,
                db_factory=db_factory,
                worker_name="test",
            )

    mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# T1-D: _run_handler() connection error → _log_worker_error 1회 + fail_run 1회
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_handler_logs_connection_warning_once_cross():
    """R: ScheduledCrawlWorker._run_handler() — connection error에서 _log_worker_error 1회 + fail_run 1회."""
    from app.worker.scheduled_worker import ScheduledCrawlWorker

    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._log_worker_error = MagicMock()
    worker._get_worker_ctx = MagicMock(return_value=MagicMock())

    mock_handler = MagicMock()
    mock_handler.target_type = "writing_task"
    mock_handler.execute = AsyncMock(side_effect=_pg_conn_err())

    mock_claimed = MagicMock()
    mock_claimed.run.id = 1
    mock_claimed.config_snapshot_patch = {}

    mock_svc = MagicMock()
    mock_db = MagicMock()

    with (
        patch("app.worker.scheduled_worker.SessionLocal", return_value=mock_db),
        patch("app.worker.scheduled_worker.TaskScheduleService", return_value=mock_svc),
    ):
        await worker._run_handler(mock_handler, MagicMock(), mock_claimed)

    # _log_worker_error 정확히 1회
    assert worker._log_worker_error.call_count == 1

    # fail_run 정확히 1회 (SessionLocal 새 세션 생성 후 호출)
    mock_svc.fail_run.assert_called_once()
