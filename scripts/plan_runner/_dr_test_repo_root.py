"""test_source-only repository root override helpers."""

from __future__ import annotations

import os
from pathlib import Path

ALLOW_TEST_REPO_ROOT_ENV = "DEV_RUNNER_ALLOW_TEST_REPO_ROOT"


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_test_repo_root(
    value: str | None,
    *,
    test_source: str | None,
    project_root: Path,
) -> Path | None:
    if not value:
        return None
    if not test_source:
        raise ValueError("test_repo_root requires test_source")
    if not _env_truthy(ALLOW_TEST_REPO_ROOT_ENV):
        raise ValueError(f"test_repo_root requires {ALLOW_TEST_REPO_ROOT_ENV}=1")

    root = Path(value).expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise ValueError(f"test_repo_root must be an existing git repo root: {root}")
    if root == Path(project_root).resolve():
        raise ValueError("test_repo_root cannot point at monitor-page root")
    return root


def read_runner_test_repo_root(redis_client, runner_id: str, *, project_root: Path) -> Path | None:
    if not runner_id:
        return None
    raw = redis_client.get(f"plan-runner:runners:{runner_id}:test_repo_root")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    test_source = redis_client.get(f"plan-runner:runners:{runner_id}:test_source")
    if isinstance(test_source, bytes):
        test_source = test_source.decode("utf-8", errors="replace")
    return resolve_test_repo_root(raw, test_source=test_source, project_root=project_root)
