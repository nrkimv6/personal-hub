from datetime import datetime

from app.models.plan_record import PlanRecord
from app.models.tracking_item import TrackingItem, TrackingItemPlanLink
from app.modules.dev_runner.services.plan_record_service import PlanRecordService
from app.modules.dev_runner.services.plan_wait_tracking_service import (
    AUTO_WAIT_PLAN_TRACKING_MARKER,
    parse_waiting_plan_signal,
    upsert_wait_tracking_for_plan,
)


def _write_plan(path, *, title="예약 검토", status="예약대기", wait_line="> 검토 예정일: 2026-06-07", summary="자동 등록 대상"):
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                f"> 상태: {status}",
                wait_line,
                f"> 요약: {summary}",
                "> 진행률: 0/3 (0%)",
                "",
                "## TODO",
                "- [ ] 대기",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_upsert_wait_tracking_right_creates_upcoming_item(test_db_session, tmp_path):
    plan_path = _write_plan(tmp_path / "2026-05-11_waiting-plan.md")

    result = upsert_wait_tracking_for_plan(
        test_db_session,
        plan_path,
        now=datetime(2026, 5, 11, 9, 0, 0),
    )

    assert result.action == "created"
    item = test_db_session.query(TrackingItem).one()
    assert item.title == "예약대기 plan: 예약 검토"
    assert item.start_at == datetime(2026, 6, 7, 0, 0, 0)
    assert item.due_at is None
    assert AUTO_WAIT_PLAN_TRACKING_MARKER in item.description
    assert result.tracking_item_id == item.id


def test_upsert_wait_tracking_boundary_dedupes_existing_open_item(test_db_session, tmp_path):
    plan_path = _write_plan(tmp_path / "2026-05-11_waiting-plan.md")
    first = upsert_wait_tracking_for_plan(test_db_session, plan_path)
    test_db_session.flush()

    _write_plan(
        plan_path,
        title="예약 검토 갱신",
        wait_line="> 검토 예정일: 2026-06-08",
        summary="갱신된 요약",
    )
    second = upsert_wait_tracking_for_plan(test_db_session, plan_path)

    assert first.tracking_item_id == second.tracking_item_id
    assert second.action == "updated"
    assert test_db_session.query(TrackingItem).count() == 1
    item = test_db_session.query(TrackingItem).one()
    assert item.title == "예약대기 plan: 예약 검토 갱신"
    assert item.start_at == datetime(2026, 6, 8, 0, 0, 0)
    assert "갱신된 요약" in item.description


def test_upsert_wait_tracking_error_skips_missing_wait_date(test_db_session, tmp_path):
    plan_path = _write_plan(
        tmp_path / "2026-05-11_missing-date.md",
        wait_line="> 요약: 날짜 없음",
    )

    result = upsert_wait_tracking_for_plan(test_db_session, plan_path)

    assert result.action == "skipped"
    assert result.reason == "missing_wait_until"
    assert test_db_session.query(TrackingItem).count() == 0
    assert test_db_session.query(PlanRecord).count() == 0


def test_upsert_wait_tracking_skips_terminal_and_hold_statuses(test_db_session, tmp_path):
    done_path = _write_plan(tmp_path / "2026-05-11_done.md", status="완료")
    hold_path = _write_plan(tmp_path / "2026-05-11_hold.md", status="보류")

    done = upsert_wait_tracking_for_plan(test_db_session, done_path)
    hold = upsert_wait_tracking_for_plan(test_db_session, hold_path)

    assert done.action == "skipped"
    assert done.reason == "terminal_status"
    assert hold.action == "skipped"
    assert hold.reason == "not_waiting_status"
    assert test_db_session.query(TrackingItem).count() == 0


def test_upsert_wait_tracking_reference_links_new_plan_record(test_db_session, tmp_path):
    plan_path = _write_plan(tmp_path / "2026-05-11_linked-plan.md")

    result = upsert_wait_tracking_for_plan(test_db_session, plan_path)

    record = test_db_session.query(PlanRecord).one()
    link = test_db_session.query(TrackingItemPlanLink).one()
    assert result.plan_record_id == record.id
    assert record.file_path == str(plan_path.resolve())
    assert link.plan_record_id == record.id
    assert link.tracking_item_id == result.tracking_item_id


def test_plan_record_sync_integration_creates_wait_tracking_without_stale_link(test_db_session, tmp_path):
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    stale_path = tmp_path / "old" / "2026-06-07_review-worktree-residue-monitoring-removal.md"
    stale_path.parent.mkdir()
    PlanRecordService(test_db_session).get_or_create(str(stale_path), title="old stale")
    plan_path = _write_plan(plan_dir / "2026-06-07_review-worktree-residue-monitoring-removal.md")
    test_db_session.flush()

    result = PlanRecordService(test_db_session).sync_all([{"path": str(plan_dir), "type": "plan"}])

    assert result["wait_tracking_created"] == 1
    item = test_db_session.query(TrackingItem).one()
    link = test_db_session.query(TrackingItemPlanLink).one()
    linked_record = test_db_session.query(PlanRecord).filter_by(id=link.plan_record_id).one()
    assert item.start_at == datetime(2026, 6, 7, 0, 0, 0)
    assert linked_record.file_path == str(plan_path.resolve())
    assert linked_record.file_path != str(stale_path.resolve())


def test_parse_waiting_plan_signal_uses_review_due_at_fallback(tmp_path):
    plan_path = tmp_path / "2026-05-11_table-fallback.md"
    plan_path.write_text(
        "\n".join(
            [
                "# 표 기반 대기",
                "> 상태: 예약대기",
                "",
                "| key | value |",
                "| --- | --- |",
                "| review_due_at | 2026-06-09T13:30:00 |",
            ]
        ),
        encoding="utf-8",
    )

    signal = parse_waiting_plan_signal(plan_path)

    assert signal.eligible is True
    assert signal.wait_until == datetime(2026, 6, 9, 13, 30, 0)
