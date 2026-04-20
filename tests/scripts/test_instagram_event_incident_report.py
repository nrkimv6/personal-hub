"""Unit tests for scripts/diagnostics/instagram_event_incident_report.py."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import instagram_event_incident_report as m  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.instagram_post import InstagramPost  # noqa: E402
from app.models.task_schedule import TaskSchedule, TaskScheduleRun  # noqa: E402
from app.modules.claude_worker.models.llm_request import LLMRequest  # noqa: E402


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return session, engine


def seed_instagram_schedule(session, schedule_id: int = 1) -> TaskSchedule:
    schedule = TaskSchedule(
        id=schedule_id,
        name=f"instagram-feed-{schedule_id}",
        target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_INTERVAL,
        schedule_value="60",
        enabled=True,
    )
    session.add(schedule)
    session.commit()
    return schedule


def test_collect_run_metrics_right_incident_window():
    session, engine = make_session()
    try:
        schedule = seed_instagram_schedule(session)
        session.add_all(
            [
                TaskScheduleRun(
                    id=11,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 16, 23, 59, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=9,
                    saved_count=3,
                ),
                TaskScheduleRun(
                    id=12,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 17, 10, 0, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=22,
                    saved_count=7,
                ),
                TaskScheduleRun(
                    id=13,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 18, 11, 0, 0),
                    status=TaskScheduleRun.STATUS_FAILED,
                    collected_count=15,
                    saved_count=0,
                    error_message="Save result failed for instagram",
                ),
            ]
        )
        session.commit()

        metrics = {
            row.metric: row
            for row in m.collect_run_metrics(
                session,
                m.build_window("incident", "2026-04-17", "2026-04-18"),
            )
        }

        assert metrics["runs_total"].count == 2
        assert metrics["runs_total"].sample_ids == [12, 13]
        assert metrics["new_saved"].count == 7
        assert metrics["total_collected"].count == 37
        assert metrics["runs_failed"].count == 1
        assert metrics["save_result_failed_runs"].count == 1
        assert metrics["save_result_failed_runs"].sample_ids == [13]
    finally:
        session.close()
        engine.dispose()


def test_collect_funnel_metrics_boundary_empty_window():
    session, engine = make_session()
    try:
        metrics = {
            row.metric: row
            for row in m.collect_funnel_metrics(
                session,
                m.build_window("incident", "2026-04-17", "2026-04-17"),
            )
        }

        assert metrics["new_posts"].count == 0
        assert metrics["event_posts"].count == 0
        assert metrics["event_posts_without_llm"].count == 0
        assert metrics["completed_requests"].count == 0
        assert metrics["completed_event_missing"].count == 0
        assert metrics["event_saved"].count == 0
        assert metrics["event_saved"].visible_count == 0
        assert metrics["event_saved"].sample_ids == []
    finally:
        session.close()
        engine.dispose()


def test_collect_funnel_metrics_error_invalid_range():
    try:
        m.build_window("incident", "2026-04-20", "2026-04-17")
        assert False, "invalid range should raise"
    except ValueError as exc:
        assert "Invalid incident window" in str(exc)


def test_collect_funnel_metrics_counts_visible_and_missing_buckets():
    session, engine = make_session()
    try:
        post_a = InstagramPost(
            id=101,
            post_id="p101",
            account="alpha",
            caption="caption",
            created_at=datetime(2026, 4, 17, 9, 0, 0),
            classified_type="event",
        )
        post_b = InstagramPost(
            id=102,
            post_id="p102",
            account="beta",
            caption="caption",
            created_at=datetime(2026, 4, 17, 9, 30, 0),
            classified_type="event",
        )
        session.add_all([post_a, post_b])
        session.flush()

        session.add_all(
            [
                LLMRequest(
                    id=201,
                    caller_type="instagram",
                    caller_id="101",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 17, 10, 0, 0),
                    processed_at=datetime(2026, 4, 17, 10, 5, 0),
                    result='{"tag":"이벤트","summary":"saved"}',
                ),
                LLMRequest(
                    id=202,
                    caller_type="instagram",
                    caller_id="102",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 17, 11, 0, 0),
                    processed_at=datetime(2026, 4, 17, 11, 5, 0),
                    result='{"tag":"이벤트","summary":"missing"}',
                ),
            ]
        )
        session.add(
            Event(
                id=301,
                title="saved event",
                event_type="event",
                source_type="instagram",
                source_instagram_post_id=101,
                created_at=datetime(2026, 4, 17, 10, 6, 0),
                event_end=date(2026, 4, 20),
            )
        )
        session.commit()

        metrics = {
            row.metric: row
            for row in m.collect_funnel_metrics(
                session,
                m.build_window("incident", "2026-04-17", "2026-04-17"),
            )
        }

        assert metrics["new_posts"].count == 2
        assert metrics["event_posts"].count == 2
        assert metrics["event_posts_with_llm"].count == 2
        assert metrics["event_posts_without_llm"].count == 0
        assert metrics["completed_requests"].count == 2
        assert metrics["completed_event_saved"].count == 1
        assert metrics["completed_event_saved"].sample_ids == [101]
        assert metrics["completed_event_missing"].count == 1
        assert metrics["completed_event_missing"].sample_ids == [102]
        assert metrics["event_saved"].count == 1
        assert metrics["event_saved"].visible_count == 1
    finally:
        session.close()
        engine.dispose()


def test_build_report_includes_control_daily_rows_and_annotations():
    session, engine = make_session()
    try:
        schedule = seed_instagram_schedule(session)
        session.add_all(
            [
                TaskScheduleRun(
                    id=21,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 12, 8, 0, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=10,
                    saved_count=4,
                ),
                TaskScheduleRun(
                    id=22,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 17, 8, 0, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=12,
                    saved_count=5,
                ),
            ]
        )
        session.add_all(
            [
                InstagramPost(
                    id=401,
                    post_id="p401",
                    account="control",
                    caption="caption",
                    created_at=datetime(2026, 4, 12, 9, 0, 0),
                    classified_type="event",
                ),
                InstagramPost(
                    id=402,
                    post_id="p402",
                    account="incident",
                    caption="caption",
                    created_at=datetime(2026, 4, 17, 9, 0, 0),
                    classified_type="event",
                ),
                LLMRequest(
                    id=501,
                    caller_type="instagram",
                    caller_id="401",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 12, 9, 30, 0),
                    processed_at=datetime(2026, 4, 12, 9, 31, 0),
                    result='{"tag":"이벤트","summary":"control"}',
                ),
                LLMRequest(
                    id=502,
                    caller_type="instagram",
                    caller_id="402",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 17, 9, 30, 0),
                    processed_at=datetime(2026, 4, 17, 9, 31, 0),
                    result='{"tag":"이벤트","summary":"incident"}',
                ),
                Event(
                    id=601,
                    title="control event",
                    event_type="event",
                    source_type="instagram",
                    source_instagram_post_id=401,
                    created_at=datetime(2026, 4, 12, 9, 40, 0),
                    event_end=date(2026, 4, 15),
                ),
                Event(
                    id=602,
                    title="incident event",
                    event_type="event",
                    source_type="instagram",
                    source_instagram_post_id=402,
                    created_at=datetime(2026, 4, 17, 9, 40, 0),
                    event_end=date(2026, 4, 20),
                ),
            ]
        )
        session.commit()

        incident = m.build_window("incident", "2026-04-17", "2026-04-17")
        control = m.build_window("control", "2026-04-12", "2026-04-12")
        excluded = m.build_window("excluded", "2026-04-14", "2026-04-16")
        report = m.build_report(
            session,
            windows=[incident, control],
            include_daily=True,
            annotations=m.build_annotations(
                windows=[incident, control],
                onset_date="2026-04-17",
                excluded_window=excluded,
                code_change_dates=["2026-04-16"],
                config_change_dates=["2026-04-17"],
                recovery_scope_label="completed-only",
            ),
        )

        assert [window["name"] for window in report["windows"]] == ["incident", "control"]
        assert "transition_rows" in report
        transition_by_period = {row["period"]: row for row in report["transition_rows"]}
        assert transition_by_period["incident"]["day"] == "2026-04-17"
        assert transition_by_period["incident"]["runs_total"] == 1
        assert transition_by_period["incident"]["event_saved"] == 1
        assert transition_by_period["control"]["day"] == "2026-04-12"
        assert transition_by_period["control"]["new_posts"] == 1

        kinds = [item["kind"] for item in report["annotations"]]
        assert kinds == [
            "onset",
            "excluded_window",
            "code_change",
            "config_change",
            "recovery_scope",
        ]
        assert report["annotations"][-1]["label"] == "completed-only"
    finally:
        session.close()
        engine.dispose()


def test_build_transition_rows_cross_checks_three_days_with_direct_queries():
    session, engine = make_session()
    try:
        schedule = seed_instagram_schedule(session)
        session.add_all(
            [
                TaskScheduleRun(
                    id=31,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 17, 7, 0, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=11,
                    saved_count=4,
                ),
                TaskScheduleRun(
                    id=32,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 18, 7, 0, 0),
                    status=TaskScheduleRun.STATUS_COMPLETED,
                    collected_count=9,
                    saved_count=2,
                ),
                TaskScheduleRun(
                    id=33,
                    schedule_id=schedule.id,
                    started_at=datetime(2026, 4, 19, 7, 0, 0),
                    status=TaskScheduleRun.STATUS_FAILED,
                    collected_count=6,
                    saved_count=0,
                ),
            ]
        )
        session.add_all(
            [
                InstagramPost(
                    id=701,
                    post_id="p701",
                    account="d1",
                    caption="caption",
                    created_at=datetime(2026, 4, 17, 8, 0, 0),
                    classified_type="event",
                ),
                InstagramPost(
                    id=702,
                    post_id="p702",
                    account="d2",
                    caption="caption",
                    created_at=datetime(2026, 4, 18, 8, 0, 0),
                    classified_type="event",
                ),
                InstagramPost(
                    id=703,
                    post_id="p703",
                    account="d3",
                    caption="caption",
                    created_at=datetime(2026, 4, 19, 8, 0, 0),
                    classified_type="event",
                ),
                LLMRequest(
                    id=801,
                    caller_type="instagram",
                    caller_id="701",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 17, 8, 30, 0),
                    processed_at=datetime(2026, 4, 17, 8, 31, 0),
                    result='{"tag":"이벤트","summary":"d1"}',
                ),
                LLMRequest(
                    id=802,
                    caller_type="instagram",
                    caller_id="702",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 18, 8, 30, 0),
                    processed_at=datetime(2026, 4, 18, 8, 31, 0),
                    result='{"tag":"이벤트","summary":"d2"}',
                ),
                LLMRequest(
                    id=803,
                    caller_type="instagram",
                    caller_id="703",
                    prompt="test",
                    status="failed",
                    requested_at=datetime(2026, 4, 19, 8, 30, 0),
                    processed_at=datetime(2026, 4, 19, 8, 31, 0),
                    result='{"tag":"이벤트","summary":"d3"}',
                ),
                Event(
                    id=901,
                    title="e1",
                    event_type="event",
                    source_type="instagram",
                    source_instagram_post_id=701,
                    created_at=datetime(2026, 4, 17, 8, 40, 0),
                    event_end=date(2026, 4, 20),
                ),
                Event(
                    id=902,
                    title="e2",
                    event_type="event",
                    source_type="instagram",
                    source_instagram_post_id=702,
                    created_at=datetime(2026, 4, 18, 8, 40, 0),
                    event_end=date(2026, 4, 18),
                ),
            ]
        )
        session.commit()

        rows = {
            row.day: row
            for row in m.build_transition_rows(
                session,
                [m.build_window("incident", "2026-04-17", "2026-04-19")],
            )
        }

        for raw_day in ("2026-04-17", "2026-04-18", "2026-04-19"):
            day = m.parse_date(raw_day)
            day_window = m.build_window("manual", raw_day, raw_day)
            direct_runs = m.collect_run_metrics(session, day_window)
            direct_funnel = m.collect_funnel_metrics(session, day_window)
            run_map = {row.metric: row for row in direct_runs}
            funnel_map = {row.metric: row for row in direct_funnel}
            row = rows[raw_day]

            assert row.runs_total == run_map["runs_total"].count
            assert row.new_saved == run_map["new_saved"].count
            assert row.new_posts == funnel_map["new_posts"].count
            assert row.completed_requests == funnel_map["completed_requests"].count
            assert row.event_saved == funnel_map["event_saved"].count
            assert row.visible_event_saved == (funnel_map["event_saved"].visible_count or 0)
    finally:
        session.close()
        engine.dispose()


def test_build_report_includes_exhaustive_samples_and_actions():
    session, engine = make_session()
    try:
        schedule = seed_instagram_schedule(session)
        run = TaskScheduleRun(
            id=41,
            schedule_id=schedule.id,
            started_at=datetime(2026, 4, 17, 7, 0, 0),
            status=TaskScheduleRun.STATUS_FAILED,
            collected_count=2,
            saved_count=0,
            stop_reason="duplicate_stop",
            error_message="Save result failed for instagram",
        )
        post_no_request = InstagramPost(
            id=801,
            post_id="p801",
            account="acc1",
            caption="caption",
            created_at=datetime(2026, 4, 17, 8, 0, 0),
            classified_type="event",
        )
        post_failed = InstagramPost(
            id=802,
            post_id="p802",
            account="acc2",
            caption="caption",
            created_at=datetime(2026, 4, 17, 8, 10, 0),
            classified_type="event",
        )
        post_missing = InstagramPost(
            id=803,
            post_id="p803",
            account="acc3",
            caption="caption",
            created_at=datetime(2026, 4, 17, 8, 20, 0),
            classified_type="event",
        )
        post_suspect = InstagramPost(
            id=804,
            post_id="p804",
            account="acc4",
            caption="이벤트 같은데 팝업으로 남은 문구",
            created_at=datetime(2026, 4, 17, 8, 30, 0),
            classified_type="popup",
        )
        session.add_all([run, post_no_request, post_failed, post_missing, post_suspect])
        session.add_all(
            [
                LLMRequest(
                    id=901,
                    caller_type="instagram",
                    caller_id="802",
                    prompt="test",
                    status="failed",
                    requested_at=datetime(2026, 4, 17, 9, 0, 0),
                    error_message="provider timeout",
                ),
                LLMRequest(
                    id=902,
                    caller_type="instagram",
                    caller_id="803",
                    prompt="test",
                    status="completed",
                    requested_at=datetime(2026, 4, 17, 9, 10, 0),
                    processed_at=datetime(2026, 4, 17, 9, 11, 0),
                    result='{"tag":"이벤트","summary":"missing"}',
                ),
            ]
        )
        session.commit()

        report = m.build_report(
            session,
            windows=[m.build_window("incident", "2026-04-17", "2026-04-17")],
            sample_limit=10,
            include_daily=False,
        )

        sample_buckets = {}
        for row in report["samples"]:
            sample_buckets.setdefault(row["bucket"], []).append(row)

        assert sample_buckets["low_ingress_run"][0]["current_state"].startswith("schedule_id=1")
        assert sample_buckets["low_ingress_run"][0]["is_exhaustive"] is True
        assert sample_buckets["no_request"][0]["item_id"] == 801
        assert sample_buckets["failed_request"][0]["item_id"] == 901
        assert sample_buckets["completed_no_event"][0]["related_id"] == 803
        assert sample_buckets["popup_or_uncategorized_suspect_event"][0]["item_id"] == 804
        assert all("needed_action" in row and row["needed_action"] for rows in sample_buckets.values() for row in rows)
    finally:
        session.close()
        engine.dispose()


def test_collect_config_timeline_reads_target_config_and_run_snapshots():
    session, engine = make_session()
    try:
        schedule = seed_instagram_schedule(session)
        schedule.created_at = datetime(2026, 4, 16, 8, 0, 0)
        schedule.updated_at = datetime(2026, 4, 16, 9, 0, 0)
        schedule.set_target_config(
            {
                "duplicate_stop_count": 25,
                "max_posts": 80,
                "service_account_id": 7,
                "llm_provider": "claude",
                "llm_model": "haiku",
            }
        )

        run = TaskScheduleRun(
            id=51,
            schedule_id=schedule.id,
            started_at=datetime(2026, 4, 17, 7, 30, 0),
            status=TaskScheduleRun.STATUS_COMPLETED,
            collected_count=12,
            saved_count=5,
        )
        run.set_config_snapshot(
            {
                "duplicate_stop_count": 20,
                "max_posts": 60,
                "service_account_id": 7,
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-mini",
            }
        )
        session.add(run)
        session.commit()

        timeline = m.collect_config_timeline(
            session,
            since_dt=datetime(2026, 4, 17, 0, 0, 0),
            until_dt=datetime(2026, 4, 18, 0, 0, 0),
        )

        timeline_by_scope = {entry.scope: entry for entry in timeline}
        assert timeline_by_scope["schedule:1"].category == "target_config"
        assert timeline_by_scope["schedule:1"].recorded_at == "2026-04-16T09:00:00"
        assert timeline_by_scope["schedule:1"].details["duplicate_stop_count"] == 25
        assert timeline_by_scope["schedule:1"].details["llm_model"] == "haiku"

        assert timeline_by_scope["run:51"].category == "config_snapshot"
        assert timeline_by_scope["run:51"].recorded_at == "2026-04-17T07:30:00"
        assert timeline_by_scope["run:51"].details["max_posts"] == 60
        assert timeline_by_scope["run:51"].details["llm_provider"] == "openai"
    finally:
        session.close()
        engine.dispose()


def test_collect_code_timeline_parses_git_log_and_errors_by_path():
    with patch.object(
        m.subprocess,
        "run",
        side_effect=[
            SimpleNamespace(
                returncode=0,
                stdout="abc123\t2026-04-16\tclassifier change\n",
                stderr="",
            ),
            SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="fatal: bad revision",
            ),
        ],
    ) as mocked_run:
        timeline = m.collect_code_timeline(
            Path("D:/repo"),
            since="2026-03-25",
            until="2026-04-20",
            watched_paths=["a.py", "b.py"],
        )

    assert mocked_run.call_count == 2
    assert timeline[0].category == "code_change"
    assert timeline[0].scope == "a.py"
    assert timeline[0].recorded_at == "2026-04-16"
    assert timeline[0].details == {"commit": "abc123", "subject": "classifier change"}
    assert timeline[1].scope == "b.py"
    assert timeline[1].recorded_at == "error"
    assert timeline[1].details["error"] == "fatal: bad revision"


def test_build_report_includes_code_and_config_timelines_and_impacts():
    session, engine = make_session()
    try:
        report = m.build_report(
            session,
            windows=[m.build_window("incident", "2026-04-17", "2026-04-17")],
            code_timeline=[
                {
                    "category": "code_change",
                    "scope": "app/modules/instagram/services/classifier_service.py",
                    "recorded_at": "2026-04-16",
                    "details": {"commit": "abc123", "subject": "change"},
                }
            ],
            config_timeline=[
                {
                    "category": "config_snapshot",
                    "scope": "run:1",
                    "recorded_at": "2026-04-17T00:00:00",
                    "details": {"llm_provider": "claude"},
                }
            ],
        )

        assert report["code_timeline"][0]["scope"].endswith("classifier_service.py")
        assert report["config_timeline"][0]["scope"] == "run:1"
        impact_paths = {row["path"] for row in report["codepath_impacts"]}
        assert "app/modules/instagram/routes/extension.py" in impact_paths
        assert "app/modules/instagram/services/llm_classifier_service.py" in impact_paths
    finally:
        session.close()
        engine.dispose()
