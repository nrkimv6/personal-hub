"""Plan Archive cross-repo index service contracts."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.modules.dev_runner.services.plan_archive_cross_repo_index_service import (
    PlanArchiveCrossRepoIndexService,
)
from app.modules.dev_runner.services.plan_archive_repo_registry import RepoRegistryEntry


@dataclass
class _Registry:
    entries: list[RepoRegistryEntry]

    def list_repos(self):
        return self.entries


class _Record:
    archived_at = None
    applied_at = None


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _make_repo(repo: Path, rel_path: str):
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('repo')\n", encoding="utf-8")
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", "feat: repo file")


def test_cross_repo_index_right_records_repo_key(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_repo(first, "app/a.py")
    _make_repo(second, "scripts/b.py")
    registry = _Registry([
        RepoRegistryEntry("first", first, "test"),
        RepoRegistryEntry("second", second, "test"),
    ])

    candidates = PlanArchiveCrossRepoIndexService(registry).collect_candidates(_Record())

    by_key = {candidate.repo_key: candidate for candidate in candidates}
    assert by_key["first"].status == "ready"
    assert by_key["second"].status == "ready"
    assert any(ref.path == "app/a.py" for ref in by_key["first"].refs)
    assert any(ref.path == "scripts/b.py" for ref in by_key["second"].refs)


def test_repo_failure_does_not_abort_batch_error(tmp_path):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _make_repo(good, "app/good.py")
    bad.mkdir()
    registry = _Registry([
        RepoRegistryEntry("good", good, "test"),
        RepoRegistryEntry("bad", bad, "test"),
    ])

    candidates = PlanArchiveCrossRepoIndexService(registry).collect_candidates(_Record())

    by_key = {candidate.repo_key: candidate for candidate in candidates}
    assert by_key["good"].status == "ready"
    assert by_key["bad"].status == "failed"
    assert "git" in (by_key["bad"].error or "").lower()


def test_skipped_repo_is_returned_without_git_call(tmp_path):
    skipped = RepoRegistryEntry("missing", tmp_path / "missing", "test", status="skipped", reason="missing")
    registry = _Registry([skipped])

    candidates = PlanArchiveCrossRepoIndexService(registry).collect_candidates(_Record())

    assert candidates[0].repo_key == "missing"
    assert candidates[0].status == "skipped"
    assert candidates[0].error == "missing"
