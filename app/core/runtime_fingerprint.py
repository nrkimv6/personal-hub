"""Runtime fingerprint helpers for API/service drift detection."""

from __future__ import annotations

import copy
import hashlib
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_SOURCE_FILES: tuple[str, ...] = (
    "app/main.py",
    "app/router_registry.py",
    "app/core/auth.py",
    "app/routes/system.py",
    "app/modules/dev_runner/routes/events.py",
    "app/modules/dev_runner/services/event_service.py",
    "app/modules/dev_runner/services/event_payload.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_rel_path(path: str | Path) -> str:
    return Path(path).as_posix()


def _resolve_project_root(project_root: str | Path | None) -> Path:
    return PROJECT_ROOT if project_root is None else Path(project_root).resolve()


def _resolve_app_mode(app_mode: str | None) -> str:
    if app_mode is not None:
        normalized = str(app_mode).strip()
        if normalized:
            return normalized

    env_app_mode = os.environ.get("APP_MODE", "").strip()
    if env_app_mode:
        return env_app_mode

    try:
        from app.config import settings

        settings_app_mode = str(getattr(settings, "APP_MODE", "")).strip()
        if settings_app_mode:
            return settings_app_mode
    except Exception:
        pass

    return "unknown"


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


def _build_runtime_fingerprint(source_fingerprint: str, app_mode: str) -> str:
    runtime_seed = "\n".join(
        [
            f"app_mode={app_mode}",
            f"source_fingerprint={source_fingerprint}",
        ]
    )
    return _sha256_bytes(runtime_seed.encode("utf-8"))


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

    normalized_app_mode = _resolve_app_mode(app_mode)
    runtime_fingerprint = _build_runtime_fingerprint(source_fingerprint, normalized_app_mode)

    return {
        "runtime_fingerprint": runtime_fingerprint,
        "source_fingerprint": source_fingerprint,
        "app_mode": normalized_app_mode,
        "pid": os.getpid() if pid is None else pid,
        "cwd": str(Path.cwd() if cwd is None else Path(cwd)),
        "python_executable": str(sys.executable if python_executable is None else python_executable),
        "python_version": platform.python_version(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_files": source_records,
    }


RUNTIME_FINGERPRINT_SNAPSHOT = build_runtime_fingerprint_snapshot()


def get_runtime_fingerprint_snapshot() -> dict[str, object]:
    """Return a copy of the cached import-time snapshot."""
    snapshot = copy.deepcopy(RUNTIME_FINGERPRINT_SNAPSHOT)
    app_mode = _resolve_app_mode(snapshot.get("app_mode") if snapshot.get("app_mode") != "unknown" else None)
    snapshot["app_mode"] = app_mode
    snapshot["runtime_fingerprint"] = _build_runtime_fingerprint(
        str(snapshot["source_fingerprint"]),
        app_mode,
    )
    return snapshot


def get_runtime_fingerprint() -> str:
    return str(get_runtime_fingerprint_snapshot()["runtime_fingerprint"])
