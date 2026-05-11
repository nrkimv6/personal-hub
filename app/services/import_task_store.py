"""In-memory task store for URL import workflows."""
from __future__ import annotations

import inspect
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel


_TASKS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_result(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize_result(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_result(item) for key, item in value.items()}
    return value


def create_import_task(kind: str, url: str) -> dict[str, Any]:
    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "kind": kind,
        "url": url,
        "status": "pending",
        "phase": "queued",
        "result": None,
        "error": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    with _LOCK:
        _TASKS[task_id] = task
    return dict(task)


def get_import_task(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


def _update_task(task_id: str, **updates: Any) -> None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updated_at"] = _now_iso()


async def run_import_task(task_id: str, operation: Callable[[], Any]) -> None:
    _update_task(
        task_id,
        status="running",
        phase="processing",
        started_at=_now_iso(),
    )
    try:
        result = operation()
        if inspect.isawaitable(result):
            result = await result
        _update_task(
            task_id,
            status="completed",
            phase="completed",
            result=_serialize_result(result),
            finished_at=_now_iso(),
        )
    except Exception as exc:
        _update_task(
            task_id,
            status="failed",
            phase="failed",
            error=str(exc),
            finished_at=_now_iso(),
        )
