"""Scheduled handler ORM boundary guard tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.models.task_schedule import TaskSchedule
from app.worker.schedule_handler_base import (
    ClaimedRun,
    ScheduleExecutionSpec,
    ScheduleHandler,
    build_schedule_execution_spec,
)


def _scheduler_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return sorted(
        list((root / "app" / "modules").glob("*/schedulers/*_schedule.py"))
        + list((root / "app" / "worker" / "schedulers").glob("*_schedule.py"))
    )


def _execute_nodes(path: Path) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "execute"
    ]


def test_claimed_run_fields_are_primitives_right():
    fields = ClaimedRun.__dataclass_fields__

    assert "run" not in fields
    claimed = ClaimedRun(run_id=1, schedule_id=2, task_name="task")
    assert isinstance(claimed.run_id, int)
    assert isinstance(claimed.schedule_id, int)


def test_build_spec_copies_target_config_re():
    schedule = TaskSchedule(
        id=7,
        name="copy-spec",
        display_name="Copy Spec",
        target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
        schedule_value="0 2 * * *",
    )
    schedule.set_target_config({"saved_search_id": 1})

    spec = build_schedule_execution_spec(schedule)
    schedule.set_target_config({"saved_search_id": 2})

    assert spec.target_config == {"saved_search_id": 1}


def test_build_spec_boundary_empty_target_config():
    schedule = TaskSchedule(
        id=8,
        name="empty-spec",
        target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_CRON,
    )

    spec = build_schedule_execution_spec(schedule)

    assert spec.target_config == {}


def test_schedule_handler_execute_signature_has_no_orm_schedule_co():
    signature = inspect.signature(ScheduleHandler.execute)
    params = list(signature.parameters.values())

    assert params[1].name == "spec"
    assert params[1].annotation == "ScheduleExecutionSpec"


def test_all_scheduler_execute_signatures_take_spec():
    for path in _scheduler_files():
        execute_nodes = _execute_nodes(path)
        assert execute_nodes, f"{path} has no execute()"
        for node in execute_nodes:
            args = node.args.args
            assert len(args) >= 2, f"{path}:{node.lineno} execute() missing spec arg"
            assert args[1].arg == "spec", f"{path}:{node.lineno} execute() must take spec"
            annotation = args[1].annotation
            assert isinstance(annotation, ast.Name), f"{path}:{node.lineno} spec must be annotated"
            assert annotation.id == "ScheduleExecutionSpec", f"{path}:{node.lineno} spec annotation mismatch"


def test_no_get_target_config_in_execute_bodies():
    for path in _scheduler_files():
        for node in _execute_nodes(path):
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if isinstance(func, ast.Attribute) and func.attr == "get_target_config":
                    raise AssertionError(f"{path}:{child.lineno} execute() calls get_target_config()")
