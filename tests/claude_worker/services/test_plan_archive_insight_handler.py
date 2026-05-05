from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.plan_archive_insight_handler import save_plan_archive_insight_result


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (PlanArchiveInsightReport.__table__, LLMRequest.__table__):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_request_and_report(db):
    report = PlanArchiveInsightReport(
        range_start=datetime(2026, 1, 1),
        range_end=datetime(2026, 1, 31),
        grouping="category",
        metrics_hash="hash",
        provider="claude",
        model="sonnet",
        status="pending",
    )
    db.add(report)
    db.flush()
    request = LLMRequest(
        caller_type="plan_archive_insight_batch",
        caller_id=str(report.id),
        prompt="prompt",
        provider="claude",
        model="sonnet",
    )
    db.add(request)
    db.flush()
    report.llm_request_id = request.id
    db.commit()
    return request, report


def test_save_insight_report_right():
    db, engine = _make_session()
    try:
        request, report = _add_request_and_report(db)
        ok = save_plan_archive_insight_result(
            db,
            request,
            {"result": {"summary": "done", "recommendations": []}, "raw_response": '{"summary":"done"}'},
        )
        db.refresh(report)
        assert ok is True
        assert report.status == "completed"
        assert report.insight_json["summary"] == "done"
    finally:
        db.close()
        engine.dispose()


def test_invalid_json_error_preserves_raw_response():
    db, engine = _make_session()
    try:
        request, report = _add_request_and_report(db)
        ok = save_plan_archive_insight_result(
            db,
            request,
            {"result": "", "raw_response": "not json"},
        )
        db.refresh(report)
        assert ok is False
        assert report.status == "failed"
        assert report.raw_response == "not json"
        assert report.error_message == "INVALID_JSON_RESPONSE"
    finally:
        db.close()
        engine.dispose()
