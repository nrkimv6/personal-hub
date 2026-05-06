import subprocess
from pathlib import Path

from app.modules.dev_runner.services.plan_archive_cross_repo_index_service import PlanArchiveCrossRepoIndexService
from app.modules.dev_runner.services.plan_archive_repo_registry import RepoRegistryEntry


class _Registry:
    def __init__(self, entries):
        self.entries = entries

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
    target.write_text("evidence\n", encoding="utf-8")
    _git(repo, "add", rel_path)
    _git(repo, "commit", "-m", "feat: cross repo evidence")


def test_cross_repo_integration_right_separates_two_git_repos(tmp_path):
    monitor = tmp_path / "monitor"
    wtools = tmp_path / "wtools"
    _make_repo(monitor, "app/modules/dev_runner/routes/plan_records.py")
    _make_repo(wtools, "common/skills/implement/SKILL.md")
    service = PlanArchiveCrossRepoIndexService(
        _Registry(
            [
                RepoRegistryEntry("monitor-page", monitor, "test"),
                RepoRegistryEntry("wtools", wtools, "test"),
            ]
        )
    )

    candidates = service.collect_candidates(_Record())

    by_key = {candidate.repo_key: candidate for candidate in candidates}
    assert by_key["monitor-page"].status == "ready"
    assert by_key["wtools"].status == "ready"
    assert by_key["monitor-page"].refs[0].repo_key == "monitor-page"
    assert by_key["wtools"].refs[0].repo_key == "wtools"


def test_cross_repo_integration_right_keeps_good_repo_when_one_fails(tmp_path):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _make_repo(good, "app/good.py")
    bad.mkdir()
    service = PlanArchiveCrossRepoIndexService(
        _Registry(
            [
                RepoRegistryEntry("good", good, "test"),
                RepoRegistryEntry("bad", bad, "test"),
            ]
        )
    )

    candidates = service.collect_candidates(_Record())

    by_key = {candidate.repo_key: candidate for candidate in candidates}
    assert by_key["good"].status == "ready"
    assert by_key["bad"].status == "failed"
