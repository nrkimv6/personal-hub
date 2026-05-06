"""Readiness checks for Plan Archive execution/profile routing DB tables."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.models.plan_archive_execution import (
    PlanArchiveExecutionAttempt,
    PlanArchiveExecutionJob,
)
from app.modules.claude_worker.models.llm_request import (
    LLMProfileAssignment,
    LLMRequestProfileClaim,
    LLMScheduleProfilePolicy,
)


REQUIRED_PLAN_ARCHIVE_EXECUTION_TABLES = (
    PlanArchiveExecutionJob.__tablename__,
    PlanArchiveExecutionAttempt.__tablename__,
    LLMRequestProfileClaim.__tablename__,
    LLMProfileAssignment.__tablename__,
    LLMScheduleProfilePolicy.__tablename__,
)


def _inspection_target(engine_or_connection: Engine | Connection | Session):
    if isinstance(engine_or_connection, Session):
        return engine_or_connection.get_bind()
    return engine_or_connection


def check_plan_archive_execution_readiness(engine_or_connection: Engine | Connection | Session) -> dict:
    """Return a structured readiness payload without mutating schema."""
    inspector = inspect(_inspection_target(engine_or_connection))
    missing_tables = [
        table_name
        for table_name in REQUIRED_PLAN_ARCHIVE_EXECUTION_TABLES
        if not inspector.has_table(table_name)
    ]
    return {
        "ok": not missing_tables,
        "required_tables": list(REQUIRED_PLAN_ARCHIVE_EXECUTION_TABLES),
        "missing_tables": missing_tables,
    }

