from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = PROJECT_ROOT / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))


class _FakeRedis:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str):
        return self._values.get(key)


def _init_repo(path: Path) -> Path:
    import subprocess

    path.mkdir()
    result = subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return path


def test_read_runner_test_repo_root_allows_persisted_api_gate_without_listener_env(tmp_path, monkeypatch):
    from _dr_test_repo_root import read_runner_test_repo_root

    monkeypatch.delenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", raising=False)
    repo = _init_repo(tmp_path / "isolated")
    redis = _FakeRedis(
        {
            "plan-runner:runners:r1:test_source": "real_dummy_plan_playwright",
            "plan-runner:runners:r1:test_repo_root": str(repo),
            "plan-runner:runners:r1:test_repo_root_allowed": "1",
        }
    )

    assert read_runner_test_repo_root(redis, "r1", project_root=PROJECT_ROOT) == repo.resolve()


def test_resolve_test_repo_root_still_requires_gate_without_persisted_allow(tmp_path, monkeypatch):
    import pytest
    from _dr_test_repo_root import resolve_test_repo_root

    monkeypatch.delenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", raising=False)
    repo = _init_repo(tmp_path / "isolated")

    with pytest.raises(ValueError, match="DEV_RUNNER_ALLOW_TEST_REPO_ROOT"):
        resolve_test_repo_root(
            str(repo),
            test_source="real_dummy_plan_playwright",
            project_root=PROJECT_ROOT,
        )
