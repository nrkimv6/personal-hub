"""WorktreeManager unit tests — RIGHT-BICEP + CORRECT"""
import subprocess
import pytest
from pathlib import Path

# add scripts/plan_runner to sys.path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "plan_runner"))

import sys
if "worktree_manager" in sys.modules: del sys.modules["worktree_manager"]
import worktree_manager
print(f"DEBUG TEST: worktree_manager file={worktree_manager.__file__}")
from worktree_manager import WorktreeManager, WorktreeError, MergeResult, ensure_main_branch


@pytest.fixture
def tmp_git_repo(tmp_path):
    """create temporary git repo (main branch)"""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "commit.gpgsign", "false"], capture_output=True, cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("test")
    (tmp_path / ".gitignore").write_text(".worktrees/\n")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))
    return tmp_path


@pytest.fixture
def worktrees_dir(tmp_git_repo):
    """worktree base_dir: .worktrees subdirectory inside repo"""
    base = tmp_git_repo / ".worktrees"
    base.mkdir(exist_ok=True)
    return base, tmp_git_repo


# ── create() ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_project_root(worktrees_dir, monkeypatch):
    base_dir, repo = worktrees_dir
    import _dr_constants
    monkeypatch.setattr(_dr_constants, 'PROJECT_ROOT', repo)

class TestWorktreeManagerCreate:
    def test_right_creates_directory(self, worktrees_dir):
        """TC-Right: directory exists after create()"""
        base_dir, repo = worktrees_dir
        path, _branch = WorktreeManager.create("abc123", base_dir)
        assert path.is_dir(), "worktree directory should exist"

    def test_right_returns_absolute_path(self, worktrees_dir):
        """TC-Right: return value is absolute path and Path.is_dir() == True"""
        base_dir, repo = worktrees_dir
        path, _branch = WorktreeManager.create("abc456", base_dir)
        assert path.is_absolute()
        assert path.is_dir()

    def test_boundary_empty_runner_id_raises(self, worktrees_dir):
        """TC-Boundary: empty runner_id raises WorktreeError"""
        base_dir, repo = worktrees_dir
        with pytest.raises(WorktreeError):
            WorktreeManager.create("", base_dir)

    def test_boundary_nonexistent_base_dir_auto_create(self, tmp_git_repo):
        """TC-Boundary: auto create base_dir if it doesn't exist"""
        base_dir = tmp_git_repo / "new" / "nested" / "worktrees"
        path, _branch = WorktreeManager.create("xyz789", base_dir)
        assert path.is_dir()

    def test_error_duplicate_runner_id_reuses(self, worktrees_dir):
        """TC-Error: calling create() twice with same runner_id reuses worktree"""
        base_dir, repo = worktrees_dir
        path1, branch1 = WorktreeManager.create("dup001", base_dir)
        (path1 / "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(path1))
        subprocess.run(["git", "commit", "-m", "test commit"], capture_output=True, cwd=str(path1))
        path2, branch2 = WorktreeManager.create("dup001", base_dir)
        assert path2.is_dir()
        assert branch1 == branch2
        assert path1 == path2
        log = subprocess.run(["git", "log", "--oneline"], capture_output=True, text=True, cwd=str(path2))
        assert "test commit" in log.stdout

    def test_create_prune_dangling_then_recreate(self, worktrees_dir):
        """TC-Error: directory gone but branch remains -> prune then recreate"""
        import shutil
        base_dir, repo = worktrees_dir
        path1, branch1 = WorktreeManager.create("prune001", base_dir)
        shutil.rmtree(str(path1))
        path2, branch2 = WorktreeManager.create("prune001", base_dir)
        assert path2.is_dir()
        assert branch2 == branch1

    def test_error_not_a_git_repo(self, tmp_path):
        import worktree_manager
        with patch("worktree_manager._run_git") as mock_run:
            mock_run.returncode = 128
            mock_run.side_effect = lambda *args, **kwargs: MagicMock(returncode=128, stderr="fatal: not a git repository")
    def test_error_not_a_git_repo(self, tmp_path):
        """TC-Error: non-git directory raises WorktreeError"""
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        base_dir = non_repo / ".worktrees"
        with pytest.raises(WorktreeError):
            WorktreeManager.create("err001", base_dir)

    def test_cross_create_then_list(self, worktrees_dir):
        """TC-Cross: runner_id present in list_worktrees() after create()"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("listtest", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees]
        assert "listtest" in runner_ids

    def test_correct_conformance_path_pattern(self, worktrees_dir):
        """TC-CORRECT-Conformance: return path follows {base_dir}/{runner_id} pattern"""
        base_dir, repo = worktrees_dir
        path, branch = WorktreeManager.create("pattest", base_dir)
        assert path == base_dir / "pattest"
        assert branch == "runner/pattest"

    def test_correct_reference_branch_name(self, worktrees_dir):
        """TC-CORRECT-Reference: branch named runner/{runner_id}"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("brtest", base_dir)
        result = subprocess.run(
            ["git", "branch", "--list", "runner/brtest"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/brtest" in result.stdout

    def test_create_E_already_exists_with_unmerged_commits_reuses_branch(self, worktrees_dir):
        """E: worktree add fail (already exists) + dir missing + unmerged commits -> reuse branch"""
        base_dir, repo = worktrees_dir
        subprocess.run(["git", "branch", "-m", "main"], capture_output=True, cwd=str(repo))
        path1, branch1 = WorktreeManager.create("unmerged001", base_dir)
        (path1 / "unmerged.txt").write_text("unmerged work")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(path1))
        subprocess.run(["git", "commit", "-m", "unmerged commit"], capture_output=True, cwd=str(path1))
        subprocess.run(["git", "worktree", "remove", str(path1), "--force"],
                       capture_output=True, cwd=str(repo))
        assert not path1.exists()

        path2, branch2 = WorktreeManager.create("unmerged001", base_dir)

        assert path2.is_dir()
        assert branch2 == branch1
        log = subprocess.run(["git", "log", "--oneline"], capture_output=True, text=True, cwd=str(path2))
        assert "unmerged commit" in log.stdout

    def test_create_C_already_exists_no_unmerged_commits_deletes_branch(self, worktrees_dir):
        """C: worktree add fail (already exists) + dir missing + no unmerged commits -> delete branch and recreate"""
        import shutil
        base_dir, repo = worktrees_dir
        path1, branch1 = WorktreeManager.create("merged001", base_dir)
        subprocess.run(["git", "worktree", "remove", str(path1), "--force"],
                       capture_output=True, cwd=str(repo))
        assert not path1.exists()

        path2, branch2 = WorktreeManager.create("merged001", base_dir)

        assert path2.is_dir()
        assert branch2 == branch1
        log = subprocess.run(
            ["git", "log", f"main..{branch2}", "--oneline"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert log.stdout.strip() == ""


# ── remove() ─────────────────────────────────────────────────────────────────

class TestWorktreeManagerRemove:
    def test_right_removes_directory_and_branch(self, worktrees_dir):
        """TC-Right: remove() deletes directory and branch"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("rmtest", base_dir)
        wt_path = base_dir / "rmtest"
        assert wt_path.is_dir()
        WorktreeManager.remove("rmtest", base_dir)
        assert not wt_path.exists()
        result = subprocess.run(
            ["git", "branch", "--list", "runner/rmtest"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/rmtest" not in result.stdout

    def test_right_returns_true(self, worktrees_dir):
        """TC-Right: return True on success"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("rmtrue", base_dir)
        result = WorktreeManager.remove("rmtrue", base_dir)
        assert result is True

    def test_boundary_nonexistent_runner_id_idempotent(self, worktrees_dir):
        """TC-Boundary: nonexistent runner_id returns True (idempotent)"""
        base_dir, repo = worktrees_dir
        result = WorktreeManager.remove("ghost999", base_dir)
        assert result is True

    def test_inverse_create_remove_not_in_list(self, worktrees_dir):
        """TC-Inverse: create -> remove -> not in list_worktrees()"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("invtest", base_dir)
        WorktreeManager.remove("invtest", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees]
        assert "invtest" not in runner_ids

    def test_correct_ordering_idempotent(self, worktrees_dir):
        """TC-CORRECT-Ordering: remove() twice is idempotent"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("idem01", base_dir)
        assert WorktreeManager.remove("idem01", base_dir) is True
        assert WorktreeManager.remove("idem01", base_dir) is True

    def test_remove_branch_param_priority(self, worktrees_dir):
        """TC-Right: branch parameter priority"""
        base_dir, repo = worktrees_dir
        wt_path = base_dir / "plan_foo"
        subprocess.run(["git", "worktree", "add", str(wt_path), "-b", "plan/foo"], capture_output=True, cwd=str(repo))
        assert wt_path.is_dir()
        result = WorktreeManager.remove("any-runner", base_dir, branch="plan/foo")
        assert result is True
        assert not wt_path.exists()
        branch_list = subprocess.run(
            ["git", "branch", "--list", "plan/foo"],
            capture_output=True, text=True, cwd=str(repo)
        ).stdout
        assert "plan/foo" not in branch_list

    def test_remove_no_branch_falls_back(self, worktrees_dir):
        """TC-Boundary: branch=None fallback to runner_id logic"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("fallback01", base_dir)
        wt_path = base_dir / "fallback01"
        assert wt_path.is_dir()
        result = WorktreeManager.remove("fallback01", base_dir, branch=None)
        assert result is True
        assert not wt_path.exists()


# ── merge_to_main() ───────────────────────────────────────────────────────────

class TestWorktreeManagerMergeToMain:
    def test_right_success_no_conflict(self, worktrees_dir):
        """TC-Right: merge success no conflict"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("mergeok", base_dir)
        wt = base_dir / "mergeok"
        (wt / "new_feature.py").write_text("x = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: new feature"], cwd=str(wt), capture_output=True)
        result = WorktreeManager.merge_to_main("mergeok", base_dir, repo)
        assert result.success is True
        assert result.conflict is False

    def test_right_changes_reflected_in_main(self, worktrees_dir):
        """TC-Right: changes reflected in main branch after merge"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("mergechk", base_dir)
        wt = base_dir / "mergechk"
        (wt / "check_file.py").write_text("check = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: check"], cwd=str(wt), capture_output=True)
        WorktreeManager.merge_to_main("mergechk", base_dir, repo)
        assert (repo / "check_file.py").exists()

    def test_error_conflict(self, worktrees_dir):
        """TC-Error: conflict detected"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("conflict1", base_dir)
        wt1 = base_dir / "conflict1"
        (wt1 / "conflict.py").write_text("version = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt1), capture_output=True)
        subprocess.run(["git", "commit", "-m", "v1"], cwd=str(wt1), capture_output=True)
        WorktreeManager.merge_to_main("conflict1", base_dir, repo)
        WorktreeManager.create("conflict2", base_dir)
        wt2 = base_dir / "conflict2"
        (wt2 / "conflict.py").write_text("version = 2\nextra = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt2), capture_output=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=str(wt2), capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=str(repo), capture_output=True)
        (repo / "conflict.py").write_text("version = 99")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "main change"], cwd=str(repo), capture_output=True)
        result = WorktreeManager.merge_to_main("conflict2", base_dir, repo)
        assert result.success is False
        assert result.conflict is True

    def test_merge_to_main_branch_param_priority(self, worktrees_dir):
        """TC-Right: branch parameter priority in merge_to_main"""
        base_dir, repo = worktrees_dir
        wt_path = base_dir / "foo"
        subprocess.run(["git", "worktree", "add", str(wt_path), "-b", "plan/foo"], capture_output=True, cwd=str(repo))
        (wt_path / "branch_priority.py").write_text("ok = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: branch priority test"], cwd=str(wt_path), capture_output=True)
        result = WorktreeManager.merge_to_main("any-runner", base_dir, repo, plan_file="bar.md", branch="plan/foo")
        assert result.success is True

    def test_merge_to_main_branch_none_falls_back_plan_file(self, worktrees_dir):
        """TC-Boundary: fallback to plan_file if branch=None"""
        base_dir, repo = worktrees_dir
        stem = "2026-01-01_test"
        wt_path = base_dir / stem
        subprocess.run(["git", "worktree", "add", str(wt_path), "-b", f"plan/{stem}"], capture_output=True, cwd=str(repo))
        (wt_path / "plan_fallback.py").write_text("x = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: plan fallback"], cwd=str(wt_path), capture_output=True)
        result = WorktreeManager.merge_to_main("any-runner", base_dir, repo, plan_file=f"{stem}.md", branch=None)
        assert result.success is True

    def test_merge_to_main_no_branch_no_plan_uses_runner_id(self, worktrees_dir):
        """TC-Boundary: fallback to runner_id logic"""
        base_dir, repo = worktrees_dir
        runner_id = "t-wtmgr-regr1"
        wt_path, branch = WorktreeManager.create(runner_id, base_dir)
        (wt_path / "regr.py").write_text("x = 2")
        subprocess.run(["git", "add", "-A"], cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: regr"], cwd=str(wt_path), capture_output=True)
        result = WorktreeManager.merge_to_main(runner_id, base_dir, repo, plan_file=None, branch=None)
        assert result.success is True

    def test_correct_cardinality_one_merge_commit(self, worktrees_dir):
        """TC-CORRECT-Cardinality: exactly one merge commit created"""
        base_dir, repo = worktrees_dir
        log_before = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(repo)
        ).stdout.strip().split("\n")
        count_before = len([l for l in log_before if l])
        WorktreeManager.create("cardinality", base_dir)
        wt = base_dir / "cardinality"
        (wt / "card.py").write_text("card = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: card"], cwd=str(wt), capture_output=True)
        WorktreeManager.merge_to_main("cardinality", base_dir, repo)
        log_after = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(repo)
        ).stdout.strip().split("\n")
        count_after = len([l for l in log_after if l])
        assert count_after == count_before + 2


# ── list_worktrees() ──────────────────────────────────────────────────────────

class TestWorktreeManagerList:
    def test_right_two_worktrees(self, worktrees_dir):
        """TC-Right: two worktrees created"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("list01", base_dir)
        WorktreeManager.create("list02", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees if w.get("runner_id")]
        assert "list01" in runner_ids
        assert "list02" in runner_ids

    def test_boundary_no_worktrees(self, tmp_git_repo):
        """TC-Boundary: zero worktrees"""
        worktrees = _list_worktrees_in_repo(tmp_git_repo)
        runner_ids = [w.get("runner_id") for w in worktrees if w.get("runner_id")]
        assert runner_ids == []

    def test_correct_conformance_keys(self, worktrees_dir):
        """TC-CORRECT-Conformance: return keys {path, branch, runner_id}"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("keycheck", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        for wt in worktrees:
            assert "path" in wt
            assert "branch" in wt
            assert "runner_id" in wt


# ── TestMergeToMainStash: Phase 2 stash-pop verification ────────────────────────

class TestMergeToMainStash:
    @pytest.fixture
    def git_repo_with_main(self, tmp_path):
        """temporary git repo with main branch"""
        subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "commit.gpgsign", "false"], capture_output=True, cwd=str(tmp_path))
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))
        return tmp_path

    def _make_feature_branch(self, repo: Path, branch: str, filename: str, content: str) -> None:
        """create feature branch and commit file"""
        subprocess.run(["git", "checkout", "-b", branch], capture_output=True, cwd=str(repo))
        (repo / filename).write_text(content)
        subprocess.run(["git", "add", filename], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", f"add {filename}"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(repo))

    def test_RIGHT_stash_pop_dirty_merge_success(self, git_repo_with_main):
        """R: dirty working tree + merge success + stash pop success"""
        repo = git_repo_with_main
        self._make_feature_branch(repo, "runner/feat1", "feat1.txt", "feat1")
        (repo / "dirty.txt").write_text("dirty work")
        result = WorktreeManager.merge_to_main("feat1", repo / ".wt", repo, branch="runner/feat1")
        assert result.success is True
        assert result.stash_pop_conflict is False
        assert (repo / "dirty.txt").exists()

    def test_RIGHT_case_a_stash_pop_conflict(self, git_repo_with_main):
        """R: merge success + stash pop conflict"""
        repo = git_repo_with_main
        (repo / "shared.txt").write_text("base")
        subprocess.run(["git", "add", "shared.txt"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "add shared"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "-b", "runner/feat2"], capture_output=True, cwd=str(repo))
        (repo / "shared.txt").write_text("branch version")
        subprocess.run(["git", "add", "shared.txt"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "branch shared"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(repo))
        (repo / "shared.txt").write_text("main dirty version")
        result = WorktreeManager.merge_to_main("feat2", repo / ".wt", repo, branch="runner/feat2")
        assert result.success is True
        assert result.stash_pop_conflict is True

    def test_RIGHT_case_b_conflict_abort_pop(self, git_repo_with_main):
        """R: merge CONFLICT -> abort + pop"""
        repo = git_repo_with_main
        (repo / "shared.txt").write_text("main line")
        subprocess.run(["git", "add", "shared.txt"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "main shared"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "-b", "runner/feat3"], capture_output=True, cwd=str(repo))
        (repo / "shared.txt").write_text("branch line")
        subprocess.run(["git", "add", "shared.txt"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "branch shared"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "checkout", "main"], capture_output=True, cwd=str(repo))
        (repo / "shared.txt").write_text("main conflict line")
        subprocess.run(["git", "add", "shared.txt"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "commit", "-m", "main conflict"], capture_output=True, cwd=str(repo))
        result = WorktreeManager.merge_to_main("feat3", repo / ".wt", repo, branch="runner/feat3")
        assert result.success is False
        assert result.conflict is True
        assert result.overwritten is False
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(repo))
        assert "<<<" not in status.stdout

    def test_BOUNDARY_clean_no_stash(self, git_repo_with_main):
        """B: clean working tree -> merge without stash"""
        repo = git_repo_with_main
        self._make_feature_branch(repo, "runner/feat4", "feat4.txt", "feat4 content")
        result = WorktreeManager.merge_to_main("feat4", repo / ".wt", repo, branch="runner/feat4")
        assert result.success is True
        assert result.stash_pop_conflict is False

    def test_BOUNDARY_overwritten_detection(self, git_repo_with_main, monkeypatch):
        repo = git_repo_with_main
        self._make_feature_branch(repo, "runner/feat5", "feat5.txt", "feat5")
        """B: overwritten error detection"""
        import subprocess as sp_module
        original_run = sp_module.run
        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "merge" in cmd and "--no-ff" in cmd:
                class FakeResult:
                    returncode = 1
                    stdout = ""
                    stderr = "error: Your local changes to the following files would be overwritten by merge"
                return FakeResult()
            return original_run(cmd, **kwargs)
        monkeypatch.setattr(sp_module, "run", mock_run)
        repo = git_repo_with_main
        result = WorktreeManager.merge_to_main("feat5", repo / ".wt", repo, branch="runner/feat5")
        assert result.overwritten is True
        assert result.success is False

    def test_ERROR_stash_pop_fail_drops(self, git_repo_with_main, monkeypatch, caplog):
        """E: merge success but stash pop fail -> drop and warning"""
        import subprocess as sp_module
        import logging
        original_run = sp_module.run
        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "stash" in cmd and len(cmd) > 2:
                if "pop" in cmd:
                    class FakePopResult:
                        returncode = 1
                        stdout = ""
                        stderr = "pop conflict"
                    return FakePopResult()
            return original_run(cmd, **kwargs)
        repo = git_repo_with_main
        self._make_feature_branch(repo, "runner/feat6", "feat6.txt", "feat6")
        (repo / "stash_me.txt").write_text("stash target")
        monkeypatch.setattr(sp_module, "run", mock_run)
        with caplog.at_level(logging.WARNING):
            result = WorktreeManager.merge_to_main("feat6", repo / ".wt", repo, branch="runner/feat6")
        assert result.stash_pop_conflict is True

    def test_ERROR_python_exception_propagates(self, git_repo_with_main, monkeypatch):
        repo = git_repo_with_main
        self._make_feature_branch(repo, "runner/feat7", "feat7.txt", "feat7")
        """E: RuntimeError during git merge -> exception in result"""
        import subprocess as sp_module
        original_run = sp_module.run
        def mock_run_raise(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 1 and cmd[0] == "git" and "merge" in cmd and "--no-ff" in cmd:
                raise RuntimeError("mock merge failure")
            return original_run(cmd, **kwargs)
        monkeypatch.setattr(sp_module, "run", mock_run_raise)
        repo = git_repo_with_main
        result = WorktreeManager.merge_to_main("feat7", repo / ".wt", repo, branch="runner/feat7")
        assert result.success is False
        assert "mock merge failure" in result.exception

    def test_ERROR_merge_result_fields_default(self):
        """E: MergeResult default values"""
        r = MergeResult(success=True, conflict=False, message="ok")
        assert r.stash_pop_conflict is False
        assert r.overwritten is False
        assert r.exception == ""


# ── validate() ───────────────────────────────────────────────────────────────

class TestWorktreeManagerValidate:
    def test_validate_R_valid_worktree(self, worktrees_dir):
        """R: valid worktree"""
        base, repo = worktrees_dir
        wt_path, _ = WorktreeManager.create("r1", base)
        assert WorktreeManager.validate(wt_path) is True

    def test_validate_E_no_git_file(self, tmp_path):
        """E: empty directory without .git file"""
        empty = tmp_path / "no_git"
        empty.mkdir()
        assert WorktreeManager.validate(empty) is False

    def test_validate_E_nonexistent_dir(self, tmp_path):
        """E: nonexistent path"""
        ghost = tmp_path / "ghost"
        assert WorktreeManager.validate(ghost) is False

    def test_validate_B_git_file_exists_but_invalid(self, tmp_path):
        """B: invalid .git file content"""
        d = tmp_path / "broken"
        d.mkdir()
        (d / ".git").write_text("garbage")
        assert WorktreeManager.validate(d) is False


# ── TestEnsureMainBranch: Phase 1 ensure_main_branch() verification ──────────────────

class TestEnsureMainBranch:
    @pytest.fixture
    def git_repo_main(self, tmp_path):
        """temp git repo with main branch"""
        subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "config", "commit.gpgsign", "false"], capture_output=True, cwd=str(tmp_path))
        (tmp_path / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))
        return tmp_path

    def test_ensure_main_branch_on_plan_branch(self, git_repo_main):
        """R: return to main from plan branch"""
        repo = git_repo_main
        subprocess.run(["git", "checkout", "-b", "plan/test-plan"], capture_output=True, cwd=str(repo))
        ensure_main_branch(repo)
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=str(repo))
        assert cur.stdout.strip() == "main"

    def test_ensure_main_branch_already_main(self, git_repo_main):
        """B: no-op if already on main"""
        repo = git_repo_main
        ensure_main_branch(repo)
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=str(repo))
        assert cur.stdout.strip() == "main"

    def test_ensure_main_branch_checkout_fail_raises(self, git_repo_main, monkeypatch):
        """E: raise WorktreeError if checkout fails"""
        import subprocess as sp_module
        repo = git_repo_main
        subprocess.run(["git", "checkout", "-b", "plan/dirty-plan"], capture_output=True, cwd=str(repo))
        original_run = sp_module.run
        def mock_checkout_fail(cmd, **kwargs):
            if isinstance(cmd, list) and "checkout" in cmd:
                class FakeResult:
                    returncode = 1
                    stdout = ""
                    stderr = "error: mock checkout failure"
                return FakeResult()
            return original_run(cmd, **kwargs)
        monkeypatch.setattr(sp_module, "run", mock_checkout_fail)
        with pytest.raises(WorktreeError, match="main"):
            ensure_main_branch(repo)


# ── Helper: list_worktrees() ─────────────────────────────────

def _list_worktrees_in_repo(repo: Path) -> list:
    """direct subprocess execution of git worktree list"""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(repo)
    )
    worktrees = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:], "branch": None, "runner_id": None}
        elif line.startswith("branch "):
            branch = line[7:].replace("refs/heads/", "")
            current["branch"] = branch
            if branch.startswith("runner/"):
                current["runner_id"] = branch[7:]
    if current:
        worktrees.append(current)
    return worktrees

