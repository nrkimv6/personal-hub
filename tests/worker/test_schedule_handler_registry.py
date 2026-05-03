"""Scheduled worker handler registry tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.task_schedule import TaskSchedule
from app.modules.dev_runner.schedulers.archive_rotation_schedule import ArchiveRotationScheduler
from app.modules.dev_runner.schedulers.auto_dev_runner_schedule import AutoDevRunnerScheduler
from app.modules.dev_runner.schedulers.devguide_staleness_schedule import DevguideStalenessScheduler
from app.modules.dev_runner.schedulers.plan_archive_schedule import PlanArchiveScheduler
from app.modules.dev_runner.schedulers.pytest_run_schedule import PytestRunScheduler
from app.modules.google_search.schedulers.search_schedule import GoogleSearchScheduler
from app.modules.instagram.schedulers.feed_schedule import InstagramFeedScheduler
from app.modules.reports.schedulers.report_schedule import ReportScheduler
from app.modules.writing.schedulers.keyword_analysis_schedule import KeywordAnalysisScheduler
from app.modules.writing.schedulers.topic_extract_schedule import TopicExtractScheduler
from app.modules.writing.schedulers.writing_source_schedule import WritingSourceScheduler
from app.modules.writing.schedulers.writing_task_schedule import WritingTaskScheduler
from app.worker.scheduled_worker import ScheduledCrawlWorker
from app.worker.schedulers.schedule_date_expire_schedule import ScheduleDateExpireScheduler


def test_handler_registry_contains_all_expected_target_types():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    targets = [handler.target_type for handler in worker._handlers]

    assert targets == [
        TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        TaskSchedule.TARGET_TYPE_WRITING_TASK,
        TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
        TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
        TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
        TaskSchedule.TARGET_TYPE_REPORT,
        TaskSchedule.TARGET_TYPE_PYTEST_RUN,
        TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE,
        TaskSchedule.TARGET_TYPE_DEVGUIDE_STALENESS,
        TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
        TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
        TaskSchedule.TARGET_TYPE_AUTO_DEV_RUNNER,
    ]


def test_handler_registry_uses_domain_scheduler_classes():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))

    assert [type(handler) for handler in worker._handlers] == [
        InstagramFeedScheduler,
        GoogleSearchScheduler,
        WritingTaskScheduler,
        WritingSourceScheduler,
        KeywordAnalysisScheduler,
        TopicExtractScheduler,
        ReportScheduler,
        PytestRunScheduler,
        PlanArchiveScheduler,
        DevguideStalenessScheduler,
        ArchiveRotationScheduler,
        ScheduleDateExpireScheduler,
        AutoDevRunnerScheduler,
    ]


@pytest.mark.asyncio
async def test_dispatch_does_not_create_tasks_when_registry_has_no_schedules():
    worker = ScheduledCrawlWorker(browser_manager=MagicMock(is_initialized=False))
    worker._create_task = MagicMock()
    handler = MagicMock()
    handler.target_type = "dummy"
    worker._handlers = [handler]

    db = MagicMock()
    svc = MagicMock()
    svc.get_schedules_by_type.return_value = []

    with patch("app.worker.scheduled_worker.SessionLocal", return_value=db), patch(
        "app.worker.scheduled_worker.TaskScheduleService",
        return_value=svc,
    ):
        await worker._dispatch_scheduled_runs()

    worker._create_task.assert_not_called()


def test_scheduled_worker_source_has_no_legacy_domain_methods():
    source_path = Path(__file__).resolve().parents[2] / "app" / "worker" / "scheduled_worker.py"
    content = source_path.read_text(encoding="utf-8")

    for legacy_name in [
        "_process_schedule",
        "_process_google_search_schedule",
        "_process_plan_archive_schedule",
        "_execute_feed_crawl",
        "_execute_google_search",
        "_process_unprocessed_plans",
        "_execute_schedule_date_expire_run",
    ]:
        assert legacy_name not in content
