import subprocess
from datetime import datetime

from app.modules.dev_runner.services.plan_archive_git_index_service import PlanArchiveGitIndexService


class _Record:
    archived_at = None
    applied_at = None


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_git_changed_refs_right_from_real_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    target = tmp_path / "app"
    target.mkdir()
    (target / "service.py").write_text("print('a')\n", encoding="utf-8")
    _git(tmp_path, "add", "app/service.py")
    _git(tmp_path, "commit", "-m", "feat: service")

    refs = PlanArchiveGitIndexService(tmp_path).collect_changed_refs(_Record())

    assert any(ref.path == "app/service.py" and ref.source_type == "git_changed" for ref in refs)


def test_git_command_failure_preserves_existing_refs_error(tmp_path):
    try:
        PlanArchiveGitIndexService(tmp_path).collect_changed_refs(_Record())
    except RuntimeError as exc:
        assert "git" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError")


def test_mentioned_vs_git_changed_are_separate_compliance(tmp_path):
    line = "--COMMIT--abc\t2026-05-05T00:00:00+00:00\nM\tapp/service.py"
    refs = PlanArchiveGitIndexService(tmp_path)._parse_name_status(line)
    assert refs[0].source_type == "git_changed"
    assert refs[0].path == "app/service.py"


def test_commit_window_boundary(tmp_path):
    class Record:
        archived_at = datetime(2026, 5, 5)
        applied_at = None

    svc = PlanArchiveGitIndexService(tmp_path)
    try:
        svc.collect_changed_refs(Record())
    except RuntimeError as exc:
        assert "git" in str(exc).lower()
