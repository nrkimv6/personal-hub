"""Generate normalized Instagram event incident metrics for fixed date windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.worker.worker import (
    extract_instagram_payload,
    instagram_payload_has_mojibake,
)


TAG_EVENT = "이벤트"
CONFIG_KEYS = ["duplicate_stop_count", "max_posts", "service_account_id", "llm_provider", "llm_model"]
WATCHED_CODE_PATHS = [
    "app/modules/instagram/services/crawl_service.py",
    "app/modules/instagram/services/post_service.py",
    "app/modules/instagram/services/classifier_service.py",
    "app/modules/instagram/services/llm_classifier_service.py",
    "app/modules/claude_worker/worker/worker.py",
]
CODEPATH_IMPACTS = [
    {
        "path": "app/modules/instagram/services/crawl_service.py",
        "function": "_save_post(post, service_account_id, crawl_run_id) -> bool",
        "impact": "status == 'created'일 때만 saved_count를 증가시켜 ingress 저점을 결정한다",
    },
    {
        "path": "app/modules/instagram/services/post_service.py",
        "function": "create_or_update_post(...) -> Tuple[Optional[InstagramPost], str]",
        "impact": "created/updated/unchanged 분기가 신규 row와 중복 row를 구분한다",
    },
    {
        "path": "app/modules/instagram/services/classifier_service.py",
        "function": "classify_post(post) -> list[dict]",
        "impact": "tag relation commit 후 _trigger_llm_classification_if_needed()를 호출해 request 생성을 연결한다",
    },
    {
        "path": "app/modules/instagram/services/classifier_service.py",
        "function": "_trigger_llm_classification_if_needed(post_id, matched_tags)",
        "impact": "event/popup tag가 있을 때 provider/model이 실린 request enqueue 경로를 연다",
    },
    {
        "path": "app/modules/instagram/routes/extension.py",
        "function": "create_post_from_extension(...) / create_posts_batch(...)",
        "impact": "extension 수집 경로도 classifier.classify_post()를 호출해 feed 수집과 같은 tag->LLM enqueue 체인을 공유한다",
    },
    {
        "path": "app/modules/instagram/services/llm_classifier_service.py",
        "function": "create_request(post_id, trigger_tag, requested_by='auto', provider=None, model=None)",
        "impact": "classifier가 읽어온 provider/model을 enqueue에 실어 request_source=instagram_{trigger_tag}로 worker 큐에 넣는다",
    },
    {
        "path": "app/modules/claude_worker/worker/worker.py",
        "function": "save_instagram_result(db, post_id, llm_result) -> bool",
        "impact": "event/popup/uncategorized entity 저장과 mark_failed fallback 경계를 결정한다",
    },
]


@dataclass(frozen=True)
class PeriodWindow:
    name: str
    since: date
    until: date

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.since, time.min)

    @property
    def end_dt_exclusive(self) -> datetime:
        return datetime.combine(self.until + timedelta(days=1), time.min)

    @property
    def visible_on(self) -> date:
        return self.until


@dataclass
class MetricRow:
    period: str
    metric: str
    timestamp_basis: str
    count: int
    visible_count: Optional[int] = None
    sample_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransitionRow:
    period: str
    day: str
    runs_total: int
    new_saved: int
    new_posts: int
    completed_requests: int
    completed_mojibake_requests: int
    event_saved: int
    visible_event_saved: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SampleRow:
    period: str
    bucket: str
    item_id: int
    current_state: str
    expected_state: str
    needed_action: str
    is_exhaustive: bool
    related_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TimelineEntry:
    category: str
    scope: str
    recorded_at: str
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Expected YYYY-MM-DD.") from exc


def build_window(name: str, since: str, until: str) -> PeriodWindow:
    since_date = parse_date(since)
    until_date = parse_date(until)
    if since_date > until_date:
        raise ValueError(
            f"Invalid {name} window: since {since_date.isoformat()} is after until {until_date.isoformat()}."
        )
    return PeriodWindow(name=name, since=since_date, until=until_date)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize Instagram incident metrics for incident/control windows."
    )
    parser.add_argument("--since", required=True, help="Incident window start date (YYYY-MM-DD).")
    parser.add_argument("--until", required=True, help="Incident window end date (YYYY-MM-DD).")
    parser.add_argument("--control-since", help="Control window start date (YYYY-MM-DD).")
    parser.add_argument("--control-until", help="Control window end date (YYYY-MM-DD).")
    parser.add_argument("--onset-date", help="Known onset date to annotate in the output.")
    parser.add_argument("--excluded-since", help="Excluded window start date (YYYY-MM-DD).")
    parser.add_argument("--excluded-until", help="Excluded window end date (YYYY-MM-DD).")
    parser.add_argument("--git-since", help="Code timeline start date (YYYY-MM-DD).")
    parser.add_argument("--git-until", help="Code timeline end date (YYYY-MM-DD).")
    parser.add_argument(
        "--code-change-date",
        action="append",
        default=[],
        help="Code change date annotation (repeatable).",
    )
    parser.add_argument(
        "--config-change-date",
        action="append",
        default=[],
        help="Config change date annotation (repeatable).",
    )
    parser.add_argument(
        "--recovery-scope-label",
        default="completed + tag=이벤트 + no event row",
        help="Short label for the current recovery-script scope.",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=5,
        help="How many sample IDs to keep per metric row. Default: 5",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Also emit day-by-day transition metrics for each window.",
    )
    return parser.parse_args()


def _build_metric(
    period: str,
    metric: str,
    timestamp_basis: str,
    count: int,
    sample_ids: list[int] | None = None,
    visible_count: Optional[int] = None,
) -> MetricRow:
    return MetricRow(
        period=period,
        metric=metric,
        timestamp_basis=timestamp_basis,
        count=int(count),
        visible_count=visible_count,
        sample_ids=sample_ids or [],
    )


def _safe_post_id(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_visible(event: Event, visible_on: date) -> bool:
    if event.status in ("ended", "cancelled"):
        return False
    return event.event_end is None or event.event_end >= visible_on


def _slice_exhaustive(items: list, sample_limit: int) -> tuple[list, bool]:
    if len(items) <= sample_limit:
        return items, True
    return items[:sample_limit], False


def collect_run_metrics(session, window: PeriodWindow, sample_limit: int = 5) -> list[MetricRow]:
    runs = (
        session.query(TaskScheduleRun)
        .join(TaskSchedule, TaskSchedule.id == TaskScheduleRun.schedule_id)
        .filter(
            TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            TaskScheduleRun.started_at >= window.start_dt,
            TaskScheduleRun.started_at < window.end_dt_exclusive,
        )
        .order_by(TaskScheduleRun.started_at.asc(), TaskScheduleRun.id.asc())
        .all()
    )

    completed_runs = [run for run in runs if run.status == TaskScheduleRun.STATUS_COMPLETED]
    failed_runs = [run for run in runs if run.status == TaskScheduleRun.STATUS_FAILED]
    save_failed_runs = [
        run
        for run in runs
        if run.error_message and "Save result failed for instagram" in run.error_message
    ]

    return [
        _build_metric(
            window.name,
            "runs_total",
            "task_schedule_runs.started_at",
            len(runs),
            [run.id for run in runs[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "runs_completed",
            "task_schedule_runs.started_at",
            len(completed_runs),
            [run.id for run in completed_runs[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "runs_failed",
            "task_schedule_runs.started_at",
            len(failed_runs),
            [run.id for run in failed_runs[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "total_collected",
            "task_schedule_runs.started_at",
            sum(run.collected_count or 0 for run in runs),
            [run.id for run in runs[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "new_saved",
            "task_schedule_runs.started_at",
            sum(run.saved_count or 0 for run in runs),
            [run.id for run in runs[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "save_result_failed_runs",
            "task_schedule_runs.started_at",
            len(save_failed_runs),
            [run.id for run in save_failed_runs[:sample_limit]],
        ),
    ]


def collect_run_samples(
    session,
    window: PeriodWindow,
    sample_limit: int = 10,
) -> list[SampleRow]:
    runs = (
        session.query(TaskScheduleRun)
        .join(TaskSchedule, TaskSchedule.id == TaskScheduleRun.schedule_id)
        .filter(
            TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            TaskScheduleRun.started_at >= window.start_dt,
            TaskScheduleRun.started_at < window.end_dt_exclusive,
        )
        .order_by(
            TaskScheduleRun.saved_count.asc(),
            TaskScheduleRun.collected_count.asc(),
            TaskScheduleRun.id.asc(),
        )
        .all()
    )
    sampled_runs, is_exhaustive = _slice_exhaustive(runs, sample_limit)
    return [
        SampleRow(
            period=window.name,
            bucket="low_ingress_run",
            item_id=run.id,
            related_id=run.schedule_id,
            current_state=(
                f"schedule_id={run.schedule_id} saved_count={run.saved_count or 0} "
                f"collected_count={run.collected_count or 0} stop_reason={run.stop_reason or '-'}"
            ),
            expected_state="incident/control 비교에서 low-ingress 원인을 설명할 수 있어야 한다",
            needed_action="config_snapshot·stop_reason·error_message를 같이 대조한다",
            is_exhaustive=is_exhaustive,
        )
        for run in sampled_runs
    ]


def collect_funnel_metrics(session, window: PeriodWindow, sample_limit: int = 5) -> list[MetricRow]:
    posts = (
        session.query(InstagramPost)
        .filter(
            InstagramPost.created_at >= window.start_dt,
            InstagramPost.created_at < window.end_dt_exclusive,
        )
        .order_by(InstagramPost.created_at.asc(), InstagramPost.id.asc())
        .all()
    )
    post_ids = [post.id for post in posts]
    event_posts = [post for post in posts if post.classified_type == "event"]
    event_post_ids = [post.id for post in event_posts]

    if post_ids:
        all_requests_for_posts = (
            session.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == "instagram",
                LLMRequest.caller_id.in_([str(post_id) for post_id in post_ids]),
            )
            .all()
        )
    else:
        all_requests_for_posts = []

    post_ids_with_llm = {
        post_id
        for post_id in (_safe_post_id(request.caller_id) for request in all_requests_for_posts)
        if post_id is not None
    }
    event_posts_with_llm = [post_id for post_id in event_post_ids if post_id in post_ids_with_llm]
    event_posts_without_llm = [post_id for post_id in event_post_ids if post_id not in post_ids_with_llm]

    requested_requests = (
        session.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == "instagram",
            LLMRequest.requested_at >= window.start_dt,
            LLMRequest.requested_at < window.end_dt_exclusive,
        )
        .order_by(LLMRequest.requested_at.asc(), LLMRequest.id.asc())
        .all()
    )
    completed_requests = [request for request in requested_requests if request.status == "completed"]
    failed_requests = [request for request in requested_requests if request.status == "failed"]

    processed_requests = (
        session.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == "instagram",
            LLMRequest.status == "completed",
            LLMRequest.processed_at >= window.start_dt,
            LLMRequest.processed_at < window.end_dt_exclusive,
        )
        .order_by(LLMRequest.processed_at.asc(), LLMRequest.id.asc())
        .all()
    )

    processed_post_ids = [
        post_id
        for post_id in (_safe_post_id(request.caller_id) for request in processed_requests)
        if post_id is not None
    ]
    event_map = {}
    if processed_post_ids:
        related_events = (
            session.query(Event)
            .filter(
                Event.source_type == "instagram",
                Event.source_instagram_post_id.in_(processed_post_ids),
            )
            .all()
        )
        event_map = {event.source_instagram_post_id: event for event in related_events}

    completed_event_saved_ids: list[int] = []
    completed_event_missing_ids: list[int] = []
    completed_mojibake_request_ids: list[int] = []
    for request in processed_requests:
        payload = extract_instagram_payload(request.result, request.raw_response)
        if instagram_payload_has_mojibake(payload, request.raw_response):
            completed_mojibake_request_ids.append(request.id)
        if not payload or payload.get("tag") != TAG_EVENT:
            continue

        post_id = _safe_post_id(request.caller_id)
        if post_id is None:
            continue

        if post_id in event_map:
            completed_event_saved_ids.append(post_id)
        else:
            completed_event_missing_ids.append(post_id)

    created_events = (
        session.query(Event)
        .filter(
            Event.source_type == "instagram",
            Event.created_at >= window.start_dt,
            Event.created_at < window.end_dt_exclusive,
        )
        .order_by(Event.created_at.asc(), Event.id.asc())
        .all()
    )
    visible_created_events = [
        event for event in created_events if _event_visible(event, window.visible_on)
    ]

    return [
        _build_metric(
            window.name,
            "new_posts",
            "instagram_posts.created_at",
            len(posts),
            post_ids[:sample_limit],
        ),
        _build_metric(
            window.name,
            "event_posts",
            "instagram_posts.created_at",
            len(event_posts),
            event_post_ids[:sample_limit],
        ),
        _build_metric(
            window.name,
            "event_posts_with_llm",
            "instagram_posts.created_at",
            len(event_posts_with_llm),
            event_posts_with_llm[:sample_limit],
        ),
        _build_metric(
            window.name,
            "event_posts_without_llm",
            "instagram_posts.created_at",
            len(event_posts_without_llm),
            event_posts_without_llm[:sample_limit],
        ),
        _build_metric(
            window.name,
            "completed_requests",
            "llm_requests.requested_at",
            len(completed_requests),
            [request.id for request in completed_requests[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "failed_requests",
            "llm_requests.requested_at",
            len(failed_requests),
            [request.id for request in failed_requests[:sample_limit]],
        ),
        _build_metric(
            window.name,
            "completed_event_saved",
            "llm_requests.processed_at",
            len(completed_event_saved_ids),
            completed_event_saved_ids[:sample_limit],
        ),
        _build_metric(
            window.name,
            "completed_event_missing",
            "llm_requests.processed_at",
            len(completed_event_missing_ids),
            completed_event_missing_ids[:sample_limit],
        ),
        _build_metric(
            window.name,
            "completed_mojibake_requests",
            "llm_requests.processed_at",
            len(completed_mojibake_request_ids),
            completed_mojibake_request_ids[:sample_limit],
        ),
        _build_metric(
            window.name,
            "event_saved",
            "events.created_at",
            len(created_events),
            [event.id for event in created_events[:sample_limit]],
            visible_count=len(visible_created_events),
        ),
    ]


def collect_bucket_samples(
    session,
    window: PeriodWindow,
    sample_limit: int = 10,
) -> list[SampleRow]:
    posts = (
        session.query(InstagramPost)
        .filter(
            InstagramPost.created_at >= window.start_dt,
            InstagramPost.created_at < window.end_dt_exclusive,
        )
        .order_by(InstagramPost.created_at.asc(), InstagramPost.id.asc())
        .all()
    )
    post_map = {post.id: post for post in posts}
    post_ids = list(post_map.keys())
    llm_requests = (
        session.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == "instagram",
            LLMRequest.requested_at >= window.start_dt,
            LLMRequest.requested_at < window.end_dt_exclusive,
        )
        .order_by(LLMRequest.requested_at.asc(), LLMRequest.id.asc())
        .all()
    )
    llm_by_post_id: dict[int, list[LLMRequest]] = {}
    for request in llm_requests:
        post_id = _safe_post_id(request.caller_id)
        if post_id is None:
            continue
        llm_by_post_id.setdefault(post_id, []).append(request)

    event_posts_without_llm = [
        post
        for post in posts
        if post.classified_type == "event" and post.id not in llm_by_post_id
    ]
    sampled_no_request, no_request_exhaustive = _slice_exhaustive(event_posts_without_llm, sample_limit)

    failed_requests = [request for request in llm_requests if request.status == "failed"]
    sampled_failed, failed_exhaustive = _slice_exhaustive(failed_requests, sample_limit)

    completed_no_event: list[tuple[LLMRequest, InstagramPost | None]] = []
    for request in llm_requests:
        if request.status != "completed":
            continue
        payload = extract_instagram_payload(request.result, request.raw_response)
        if not payload or payload.get("tag") != TAG_EVENT:
            continue
        post_id = _safe_post_id(request.caller_id)
        if post_id is None:
            continue
        existing_event = (
            session.query(Event)
            .filter(
                Event.source_type == "instagram",
                Event.source_instagram_post_id == post_id,
            )
            .first()
        )
        if existing_event is None:
            completed_no_event.append((request, post_map.get(post_id)))
    sampled_completed_no_event, completed_no_event_exhaustive = _slice_exhaustive(
        completed_no_event,
        sample_limit,
    )

    suspicious_non_event_posts = [
        post
        for post in posts
        if post.classified_type in ("popup", "uncategorized")
        and "이벤트" in (post.caption or "")
    ]
    sampled_suspicious, suspicious_exhaustive = _slice_exhaustive(
        suspicious_non_event_posts,
        sample_limit,
    )

    rows: list[SampleRow] = []
    rows.extend(
        SampleRow(
            period=window.name,
            bucket="no_request",
            item_id=post.id,
            current_state=f"classified_type=event created_at={post.created_at.isoformat()} llm_request=missing",
            expected_state="event-tagged post는 llm_request를 최소 1건 가져야 한다",
            needed_action="classify_post -> _trigger_llm_classification_if_needed enqueue 경로를 점검한다",
            is_exhaustive=no_request_exhaustive,
        )
        for post in sampled_no_request
    )
    rows.extend(
        SampleRow(
            period=window.name,
            bucket="failed_request",
            item_id=request.id,
            related_id=_safe_post_id(request.caller_id),
            current_state=f"status=failed error_message={request.error_message or '-'}",
            expected_state="event 관련 request는 completed 또는 재시도 가능 상태여야 한다",
            needed_action="worker error_message와 provider/model drift를 함께 대조한다",
            is_exhaustive=failed_exhaustive,
        )
        for request in sampled_failed
    )
    rows.extend(
        SampleRow(
            period=window.name,
            bucket="completed_no_event",
            item_id=request.id,
            related_id=post.id if post else _safe_post_id(request.caller_id),
            current_state=(
                f"status=completed payload.tag=이벤트 entity=missing post_id="
                f"{post.id if post else request.caller_id}"
            ),
            expected_state="completed event payload는 Event row 또는 relink 결과를 가져야 한다",
            needed_action="recover script 대상인지, save-path 실패인지 구분한다",
            is_exhaustive=completed_no_event_exhaustive,
        )
        for request, post in sampled_completed_no_event
    )
    rows.extend(
        SampleRow(
            period=window.name,
            bucket="popup_or_uncategorized_suspect_event",
            item_id=post.id,
            current_state=f"classified_type={post.classified_type} caption_contains=이벤트",
            expected_state="이 bucket은 실제 non-event인지 수동 샘플 검토가 필요하다",
            needed_action="LLM raw_response와 최종 entity를 같이 확인한다",
            is_exhaustive=suspicious_exhaustive,
        )
        for post in sampled_suspicious
    )
    return rows


def collect_daily_transition_metrics(
    session,
    window: PeriodWindow,
    sample_limit: int = 5,
) -> list[MetricRow]:
    rows: list[MetricRow] = []
    current_day = window.since
    while current_day <= window.until:
        day_window = PeriodWindow(
            name=f"{window.name}:{current_day.isoformat()}",
            since=current_day,
            until=current_day,
        )
        rows.extend(
            row
            for row in collect_run_metrics(session, day_window, sample_limit)
            if row.metric in {"runs_total", "new_saved"}
        )
        rows.extend(
            row
            for row in collect_funnel_metrics(session, day_window, sample_limit)
            if row.metric in {"new_posts", "completed_requests", "completed_mojibake_requests", "event_saved"}
        )
        current_day += timedelta(days=1)
    return rows


def build_transition_rows(
    session,
    windows: list[PeriodWindow],
    sample_limit: int = 5,
) -> list[TransitionRow]:
    rows: list[TransitionRow] = []
    for window in windows:
        current_day = window.since
        while current_day <= window.until:
            day_window = PeriodWindow(
                name=window.name,
                since=current_day,
                until=current_day,
            )
            run_metrics = {
                row.metric: row
                for row in collect_run_metrics(session, day_window, sample_limit)
            }
            funnel_metrics = {
                row.metric: row
                for row in collect_funnel_metrics(session, day_window, sample_limit)
            }
            event_saved = funnel_metrics["event_saved"]
            rows.append(
                TransitionRow(
                    period=window.name,
                    day=current_day.isoformat(),
                    runs_total=run_metrics["runs_total"].count,
                    new_saved=run_metrics["new_saved"].count,
                    new_posts=funnel_metrics["new_posts"].count,
                    completed_requests=funnel_metrics["completed_requests"].count,
                    completed_mojibake_requests=funnel_metrics["completed_mojibake_requests"].count,
                    event_saved=event_saved.count,
                    visible_event_saved=event_saved.visible_count or 0,
                )
            )
            current_day += timedelta(days=1)
    return rows


def build_annotations(
    *,
    windows: list[PeriodWindow],
    onset_date: Optional[str] = None,
    excluded_window: Optional[PeriodWindow] = None,
    code_change_dates: list[str] | None = None,
    config_change_dates: list[str] | None = None,
    recovery_scope_label: str = "completed + tag=이벤트 + no event row",
) -> list[dict]:
    annotations: list[dict] = []
    if onset_date:
        annotations.append(
            {"kind": "onset", "date": parse_date(onset_date).isoformat(), "label": "incident onset"}
        )
    if excluded_window:
        annotations.append(
            {
                "kind": "excluded_window",
                "since": excluded_window.since.isoformat(),
                "until": excluded_window.until.isoformat(),
                "label": "excluded analysis window",
            }
        )
    for raw_date in code_change_dates or []:
        annotations.append(
            {"kind": "code_change", "date": parse_date(raw_date).isoformat(), "label": "code change"}
        )
    for raw_date in config_change_dates or []:
        annotations.append(
            {"kind": "config_change", "date": parse_date(raw_date).isoformat(), "label": "config change"}
        )
    if windows:
        annotations.append(
            {
                "kind": "recovery_scope",
                "label": recovery_scope_label,
                "covers_periods": [window.name for window in windows],
            }
        )
    return annotations


def collect_code_timeline(
    repo_root: Path,
    since: str,
    until: str,
    watched_paths: list[str] | None = None,
) -> list[TimelineEntry]:
    timeline: list[TimelineEntry] = []
    for path in watched_paths or WATCHED_CODE_PATHS:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                f"--since={since}",
                f"--until={until}",
                "--date=short",
                "--pretty=format:%H%x09%ad%x09%s",
                "--",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            timeline.append(
                TimelineEntry(
                    category="code_change",
                    scope=path,
                    recorded_at="error",
                    details={"error": (result.stderr or result.stdout or "").strip()},
                )
            )
            continue

        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            commit_sha, commit_date, subject = parts
            timeline.append(
                TimelineEntry(
                    category="code_change",
                    scope=path,
                    recorded_at=commit_date,
                    details={"commit": commit_sha, "subject": subject},
                )
            )
    return timeline


def collect_config_timeline(
    session,
    since_dt: datetime,
    until_dt: datetime,
    keys: list[str] | None = None,
) -> list[TimelineEntry]:
    wanted_keys = keys or CONFIG_KEYS
    timeline: list[TimelineEntry] = []

    schedules = (
        session.query(TaskSchedule)
        .filter(TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED)
        .order_by(TaskSchedule.id.asc())
        .all()
    )
    for schedule in schedules:
        config = schedule.get_target_config()
        timeline.append(
            TimelineEntry(
                category="target_config",
                scope=f"schedule:{schedule.id}",
                recorded_at=(schedule.updated_at or schedule.created_at or datetime.min).isoformat(),
                details={key: config.get(key) for key in wanted_keys},
            )
        )

    runs = (
        session.query(TaskScheduleRun)
        .join(TaskSchedule, TaskSchedule.id == TaskScheduleRun.schedule_id)
        .filter(
            TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            TaskScheduleRun.started_at >= since_dt,
            TaskScheduleRun.started_at < until_dt,
        )
        .order_by(TaskScheduleRun.started_at.asc(), TaskScheduleRun.id.asc())
        .all()
    )
    for run in runs:
        snapshot = run.get_config_snapshot()
        timeline.append(
            TimelineEntry(
                category="config_snapshot",
                scope=f"run:{run.id}",
                recorded_at=run.started_at.isoformat(),
                details={key: snapshot.get(key) for key in wanted_keys},
            )
        )

    return timeline


def build_report(
    session,
    windows: list[PeriodWindow],
    sample_limit: int = 5,
    include_daily: bool = False,
    annotations: list[dict] | None = None,
    code_timeline: list[dict] | None = None,
    config_timeline: list[dict] | None = None,
) -> dict:
    metrics: list[dict] = []
    for window in windows:
        metrics.extend(
            row.to_dict() for row in collect_run_metrics(session, window, sample_limit)
        )
        metrics.extend(
            row.to_dict() for row in collect_funnel_metrics(session, window, sample_limit)
        )
        if include_daily:
            metrics.extend(
                row.to_dict()
                for row in collect_daily_transition_metrics(session, window, sample_limit)
            )

    report = {
        "windows": [
            {
                "name": window.name,
                "since": window.since.isoformat(),
                "until": window.until.isoformat(),
            }
            for window in windows
        ],
        "metrics": metrics,
    }
    if include_daily:
        report["transition_rows"] = [
            row.to_dict()
            for row in build_transition_rows(session, windows, sample_limit)
        ]
    if annotations:
        report["annotations"] = annotations
    report["samples"] = [
        row.to_dict()
        for window in windows
        for row in (
            collect_run_samples(session, window, max(sample_limit, 10))
            + collect_bucket_samples(session, window, max(sample_limit, 10))
        )
    ]
    if code_timeline is not None:
        report["code_timeline"] = code_timeline
    if config_timeline is not None:
        report["config_timeline"] = config_timeline
    report["codepath_impacts"] = CODEPATH_IMPACTS
    return report


def main() -> int:
    args = parse_args()
    try:
        incident_window = build_window("incident", args.since, args.until)
        windows = [incident_window]
        if args.control_since or args.control_until:
            if not (args.control_since and args.control_until):
                raise ValueError("Both --control-since and --control-until are required together.")
            windows.append(build_window("control", args.control_since, args.control_until))
        excluded_window = None
        if args.excluded_since or args.excluded_until:
            if not (args.excluded_since and args.excluded_until):
                raise ValueError("Both --excluded-since and --excluded-until are required together.")
            excluded_window = build_window("excluded", args.excluded_since, args.excluded_until)
        git_since = args.git_since or "2026-03-25"
        git_until = args.git_until or args.until
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    session = SessionLocal()
    try:
        report = build_report(
            session,
            windows=windows,
            sample_limit=max(args.sample_limit, 0),
            include_daily=args.daily,
            annotations=build_annotations(
                windows=windows,
                onset_date=args.onset_date,
                excluded_window=excluded_window,
                code_change_dates=args.code_change_date,
                config_change_dates=args.config_change_date,
                recovery_scope_label=args.recovery_scope_label,
            ),
            code_timeline=[
                entry.to_dict()
                for entry in collect_code_timeline(REPO_ROOT, git_since, git_until)
            ],
            config_timeline=[
                entry.to_dict()
                for entry in collect_config_timeline(
                    session,
                    since_dt=min(window.start_dt for window in windows),
                    until_dt=max(window.end_dt_exclusive for window in windows),
                )
            ],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
