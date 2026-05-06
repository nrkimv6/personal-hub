"""Runtime fingerprint helpers for API/service drift detection.

`app_mode`는 settings snapshot이 아니라 현재 프로세스 env(APP_MODE)를 기준으로 기록한다.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()

DEFAULT_SOURCE_FILES: tuple[str, ...] = (
    "app/main.py",
    "app/router_registry.py",
    "app/core/auth.py",
    "app/routes/system.py",
    "app/modules/dev_runner/routes/events.py",
    "app/modules/dev_runner/services/event_service.py",
    "app/modules/dev_runner/services/event_payload.py",
)

WORKER_SOURCE_FILES: tuple[str, ...] = (
    "app/worker/main.py",
    "app/worker/scheduled_worker.py",
    "app/worker/schedule_handler_base.py",
    "app/modules/instagram/services/scheduler.py",
    "app/modules/instagram/schedulers/feed_schedule.py",
    "app/modules/instagram/services/crawl_service.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_rel_path(path: str | Path) -> str:
    return Path(path).as_posix()


def _resolve_project_root(project_root: str | Path | None) -> Path:
    return PROJECT_ROOT if project_root is None else Path(project_root).resolve()


def _collect_source_files(project_root: Path, source_files: Sequence[str | Path]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for source_file in source_files:
        rel_path = _normalize_rel_path(source_file)
        absolute_path = project_root / rel_path
        record: dict[str, object] = {"path": rel_path}
        if absolute_path.exists():
            record["sha256"] = _sha256_bytes(absolute_path.read_bytes())
            record["size_bytes"] = absolute_path.stat().st_size
            record["present"] = True
        else:
            record["sha256"] = None
            record["size_bytes"] = None
            record["present"] = False
        items.append(record)
    return items


def build_runtime_fingerprint_snapshot(
    *,
    project_root: str | Path | None = None,
    app_mode: str | None = None,
    source_files: Sequence[str | Path] | None = None,
    pid: int | None = None,
    cwd: str | Path | None = None,
    python_executable: str | Path | None = None,
) -> dict[str, object]:
    """Build a stable runtime snapshot from source files and process metadata."""
    root = _resolve_project_root(project_root)
    files = list(source_files or DEFAULT_SOURCE_FILES)
    source_records = _collect_source_files(root, files)

    source_seed = "\n".join(f"{item['path']}={item['sha256']}" for item in source_records)
    source_fingerprint = _sha256_bytes(source_seed.encode("utf-8"))

    normalized_app_mode = (app_mode or os.environ.get("APP_MODE") or "unknown").strip() or "unknown"
    normalized_pid = os.getpid() if pid is None else pid
    normalized_cwd = str(Path.cwd() if cwd is None else Path(cwd))
    normalized_python_executable = str(sys.executable if python_executable is None else python_executable)
    runtime_seed = "\n".join(
        [
            f"app_mode={normalized_app_mode}",
            f"source_fingerprint={source_fingerprint}",
            f"pid={normalized_pid}",
            f"cwd={normalized_cwd}",
            f"python_executable={normalized_python_executable}",
            f"process_started_at={PROCESS_STARTED_AT}",
        ]
    )
    runtime_fingerprint = _sha256_bytes(runtime_seed.encode("utf-8"))

    return {
        "runtime_fingerprint": runtime_fingerprint,
        "source_fingerprint": source_fingerprint,
        "app_mode": normalized_app_mode,
        "pid": normalized_pid,
        "cwd": normalized_cwd,
        "python_executable": normalized_python_executable,
        "python_version": platform.python_version(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_records,
    }


RUNTIME_FINGERPRINT_SNAPSHOT = build_runtime_fingerprint_snapshot()


def get_runtime_fingerprint_snapshot(
    *,
    project_root: str | Path | None = None,
    app_mode: str | None = None,
    source_files: Sequence[str | Path] | None = None,
    pid: int | None = None,
    cwd: str | Path | None = None,
    python_executable: str | Path | None = None,
) -> dict[str, object]:
    """Return a fresh snapshot for the current process/runtime state."""
    return build_runtime_fingerprint_snapshot(
        project_root=project_root,
        app_mode=app_mode,
        source_files=source_files,
        pid=pid,
        cwd=cwd,
        python_executable=python_executable,
    )


def get_worker_runtime_fingerprint_snapshot(
    *,
    project_root: str | Path | None = None,
    app_mode: str | None = None,
    pid: int | None = None,
    cwd: str | Path | None = None,
    python_executable: str | Path | None = None,
) -> dict[str, object]:
    """Return a fresh worker-focused snapshot including scheduler source files."""
    return build_runtime_fingerprint_snapshot(
        project_root=project_root,
        app_mode=app_mode,
        source_files=WORKER_SOURCE_FILES,
        pid=pid,
        cwd=cwd,
        python_executable=python_executable,
    )


def get_runtime_fingerprint() -> str:
    return str(get_runtime_fingerprint_snapshot()["runtime_fingerprint"])
