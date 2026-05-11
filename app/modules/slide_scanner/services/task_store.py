"""In-memory task state for slide scanner long-running actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks


_tasks: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_task(kind: str, background_tasks: BackgroundTasks, runner: Callable[[], Any]) -> dict[str, str]:
    task_id = str(uuid4())
    _tasks[task_id] = {
        "task_id": task_id,
        "kind": kind,
        "status": "queued",
        "result": None,
        "error_message": None,
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
    }
    background_tasks.add_task(_run_task, task_id, runner)
    return {"task_id": task_id, "status": "queued"}


def get_task(task_id: str) -> dict[str, Any] | None:
    return _tasks.get(task_id)


def _run_task(task_id: str, runner: Callable[[], Any]) -> None:
    task = _tasks.get(task_id)
    if task is None:
        return
    task["status"] = "running"
    task["started_at"] = _now_iso()
    try:
        result = runner()
        task["status"] = "completed"
        task["result"] = dict(result or {})
        task["completed_at"] = _now_iso()
    except Exception as exc:  # noqa: BLE001
        task["status"] = "failed"
        task["error_message"] = str(exc)
        task["completed_at"] = _now_iso()
