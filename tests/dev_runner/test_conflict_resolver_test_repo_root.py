from __future__ import annotations

import subprocess
from pathlib import Path

import fakeredis

from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_conflict_resolver_test_source_uses_test_repo_root(tmp_path, monkeypatch):
    bootstrap_plan_runner_modules()
    import _dr_subprocess as mod

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    resolver = tmp_path / "resolver.py"
    resolver.write_text("print('resolved')\n", encoding="utf-8")

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    runner_id = "t-conflict-root"
    redis_client.set(f"plan-runner:runners:{runner_id}:test_source", "conflict-root")
    redis_client.set(f"plan-runner:runners:{runner_id}:test_repo_root", str(repo))

    captured = {}

    def fake_streaming(*, cmd, env, cwd, pub_fn, tag, timeout):
        captured["cmd"] = cmd
        captured["env"] = env
        captured["cwd"] = cwd
        captured["tag"] = tag
        captured["timeout"] = timeout
        return {"success": True, "message": "ok", "output": "ok"}

    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    monkeypatch.setenv("DEV_RUNNER_TEST_CONFLICT_RESOLVER_SCRIPT", str(resolver))
    monkeypatch.setattr(mod, "_run_subprocess_streaming", fake_streaming)

    result = mod._launch_conflict_resolver_process(
        runner_id=runner_id,
        branch=f"runner/{runner_id}",
        worktree_path=repo / ".worktrees" / runner_id,
        redis_client=redis_client,
        needs_remerge=True,
    )

    assert result["success"] is True
    assert str(resolver.resolve()) in captured["cmd"]
    assert "--project-dir" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--project-dir") + 1] == str(repo.resolve())
    assert captured["env"]["PLAN_RUNNER_PROJECT_ROOT"] == str(repo.resolve())
    assert "--needs-remerge" in captured["cmd"]
