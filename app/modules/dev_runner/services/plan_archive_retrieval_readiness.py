"""Readiness checks for Plan Archive retrieval DB tables."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.plan_record import (
    PlanRecordChunk,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)


REQUIRED_RETRIEVAL_TABLES = (
    PlanRecordChunk.__tablename__,
    PlanRecordFileRef.__tablename__,
    PlanRecordRelation.__tablename__,
    PlanRecordSearchRun.__tablename__,
)


def check_plan_archive_retrieval_tables(session: Session) -> list[str]:
    """Return missing Plan Archive retrieval table names without mutating schema."""
    bind = session.get_bind()
    inspector = inspect(bind)
    return [
        table_name
        for table_name in REQUIRED_RETRIEVAL_TABLES
        if not inspector.has_table(table_name)
    ]


def get_plan_archive_retrieval_readiness(session: Session) -> dict:
    """Return a structured readiness payload for API/UI callers."""
    missing_tables = check_plan_archive_retrieval_tables(session)
    return {
        "ok": not missing_tables,
        "required_tables": list(REQUIRED_RETRIEVAL_TABLES),
        "missing_tables": missing_tables,
    }
