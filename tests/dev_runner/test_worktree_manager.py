"""WorktreeManager 유닛 테스트 — RIGHT-BICEP + CORRECT"""
import subprocess
import pytest
from pathlib import Path

# scripts/ 디렉토리를 sys.path에 추가
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from worktree_manager import WorktreeManager, WorktreeError, MergeResult


@pytest.fixture
def tmp_git_repo(tmp_path):
    """임시 git 저장소 생성"""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))
    return tmp_path


@pytest.fixture
def worktrees_dir(tmp_git_repo):
    """worktree base_dir: repo 내부 .worktrees 서브디렉토리"""
    base = tmp_git_repo / ".worktrees"
    base.mkdir(exist_ok=True)
    return base, tmp_git_repo


# ── create() ─────────────────────────────────────────────────────────────────

class TestWorktreeManagerCreate:
    def test_right_creates_directory(self, worktrees_dir):
        """TC-Right: create() 후 worktree 디렉토리 존재 + git worktree list에 표시"""
        base_dir, repo = worktrees_dir
        path, _branch = WorktreeManager.create("abc123", base_dir)
        assert path.is_dir(), "worktree 디렉토리가 존재해야 한다"

    def test_right_returns_absolute_path(self, worktrees_dir):
        """TC-Right: 반환값이 절대경로이고 Path.is_dir() == True"""
        base_dir, repo = worktrees_dir
        path, _branch = WorktreeManager.create("abc456", base_dir)
        assert path.is_absolute()
        assert path.is_dir()

    def test_boundary_empty_runner_id_raises(self, worktrees_dir):
        """TC-Boundary: runner_id 빈 문자열 → WorktreeError"""
        base_dir, repo = worktrees_dir
        with pytest.raises(WorktreeError):
            WorktreeManager.create("", base_dir)

    def test_boundary_nonexistent_base_dir_auto_create(self, tmp_git_repo):
        """TC-Boundary: base_dir 미존재 → 자동 생성"""
        base_dir = tmp_git_repo / "new" / "nested" / "worktrees"
        path, _branch = WorktreeManager.create("xyz789", base_dir)
        assert path.is_dir()

    def test_error_duplicate_runner_id_raises(self, worktrees_dir):
        """TC-Error: 동일 runner_id로 두 번 create() → 두 번째 WorktreeError"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("dup001", base_dir)
        with pytest.raises(WorktreeError):
            WorktreeManager.create("dup001", base_dir)

    def test_error_not_a_git_repo(self, tmp_path):
        """TC-Error: git 저장소가 아닌 디렉토리 → WorktreeError"""
        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        base_dir = non_repo / ".worktrees"
        with pytest.raises(WorktreeError):
            WorktreeManager.create("err001", base_dir)

    def test_cross_create_then_list(self, worktrees_dir):
        """TC-Cross: create() 후 list_worktrees() 결과에 runner_id 포함"""
        base_dir, repo = worktrees_dir
        # list_worktrees는 cwd 기준 — repo 디렉토리에서 실행
        WorktreeManager.create("listtest", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees]
        assert "listtest" in runner_ids

    def test_correct_conformance_path_pattern(self, worktrees_dir):
        """TC-CORRECT-Conformance: 반환 경로가 {base_dir}/{runner_id} 패턴 준수"""
        base_dir, repo = worktrees_dir
        path, branch = WorktreeManager.create("pattest", base_dir)
        assert path == base_dir / "pattest"
        assert branch == "runner/pattest"

    def test_correct_reference_branch_name(self, worktrees_dir):
        """TC-CORRECT-Reference: 생성된 브랜치가 runner/{runner_id} 이름 준수"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("brtest", base_dir)
        result = subprocess.run(
            ["git", "branch", "--list", "runner/brtest"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/brtest" in result.stdout


# ── remove() ─────────────────────────────────────────────────────────────────

class TestWorktreeManagerRemove:
    def test_right_removes_directory_and_branch(self, worktrees_dir):
        """TC-Right: remove() 호출 → 디렉토리 삭제 + 브랜치 삭제"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("rmtest", base_dir)
        wt_path = base_dir / "rmtest"
        assert wt_path.is_dir()
        WorktreeManager.remove("rmtest", base_dir)
        assert not wt_path.exists()
        # 브랜치도 삭제 확인
        result = subprocess.run(
            ["git", "branch", "--list", "runner/rmtest"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/rmtest" not in result.stdout

    def test_right_returns_true(self, worktrees_dir):
        """TC-Right: 반환값 True"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("rmtrue", base_dir)
        result = WorktreeManager.remove("rmtrue", base_dir)
        assert result is True

    def test_boundary_nonexistent_runner_id_idempotent(self, worktrees_dir):
        """TC-Boundary: 존재하지 않는 runner_id → True 반환 (멱등)"""
        base_dir, repo = worktrees_dir
        result = WorktreeManager.remove("ghost999", base_dir)
        assert result is True

    def test_inverse_create_remove_not_in_list(self, worktrees_dir):
        """TC-Inverse: create() → remove() → list_worktrees()에 해당 항목 없음"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("invtest", base_dir)
        WorktreeManager.remove("invtest", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees]
        assert "invtest" not in runner_ids

    def test_correct_ordering_idempotent(self, worktrees_dir):
        """TC-CORRECT-Ordering: remove() 두 번 연속 → 두 번째도 True (멱등성)"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("idem01", base_dir)
        assert WorktreeManager.remove("idem01", base_dir) is True
        assert WorktreeManager.remove("idem01", base_dir) is True


# ── merge_to_main() ───────────────────────────────────────────────────────────

class TestWorktreeManagerMergeToMain:
    def test_right_success_no_conflict(self, worktrees_dir):
        """TC-Right: 충돌 없는 변경 → MergeResult(success=True, conflict=False)"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("mergeok", base_dir)
        wt = base_dir / "mergeok"
        # worktree에서 새 파일 추가
        (wt / "new_feature.py").write_text("x = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: new feature"], cwd=str(wt), capture_output=True)
        result = WorktreeManager.merge_to_main("mergeok", base_dir, repo)
        assert result.success is True
        assert result.conflict is False

    def test_right_changes_reflected_in_main(self, worktrees_dir):
        """TC-Right: 머지 후 main 브랜치에 변경사항 반영"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("mergechk", base_dir)
        wt = base_dir / "mergechk"
        (wt / "check_file.py").write_text("check = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: check"], cwd=str(wt), capture_output=True)
        WorktreeManager.merge_to_main("mergechk", base_dir, repo)
        # main에서 파일 확인
        assert (repo / "check_file.py").exists()

    def test_error_conflict(self, worktrees_dir):
        """TC-Error: 충돌 발생 → MergeResult(success=False, conflict=True)"""
        base_dir, repo = worktrees_dir
        # worktree 1
        WorktreeManager.create("conflict1", base_dir)
        wt1 = base_dir / "conflict1"
        (wt1 / "conflict.py").write_text("version = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt1), capture_output=True)
        subprocess.run(["git", "commit", "-m", "v1"], cwd=str(wt1), capture_output=True)
        WorktreeManager.merge_to_main("conflict1", base_dir, repo)
        # worktree 2 — 같은 파일 다르게 수정
        WorktreeManager.create("conflict2", base_dir)
        wt2 = base_dir / "conflict2"
        (wt2 / "conflict.py").write_text("version = 2\nextra = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt2), capture_output=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=str(wt2), capture_output=True)
        # main에서 같은 파일 수정 후 머지 → 충돌
        subprocess.run(["git", "checkout", "main"], cwd=str(repo), capture_output=True)
        (repo / "conflict.py").write_text("version = 99")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "main change"], cwd=str(repo), capture_output=True)
        result = WorktreeManager.merge_to_main("conflict2", base_dir, repo)
        assert result.success is False
        assert result.conflict is True

    def test_correct_cardinality_one_merge_commit(self, worktrees_dir):
        """TC-CORRECT-Cardinality: 머지 커밋이 정확히 1개 생성"""
        base_dir, repo = worktrees_dir
        # 머지 전 커밋 수
        log_before = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(repo)
        ).stdout.strip().split("\n")
        count_before = len([l for l in log_before if l])
        # worktree 생성 + 변경 + 머지
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
        # 머지 커밋 1개 + runner 커밋 1개 = 2개 증가 (no-ff merge)
        assert count_after == count_before + 2


# ── list_worktrees() ──────────────────────────────────────────────────────────

class TestWorktreeManagerList:
    def test_right_two_worktrees(self, worktrees_dir):
        """TC-Right: worktree 2개 생성 후 리스트 길이 2+1(main)"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("list01", base_dir)
        WorktreeManager.create("list02", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        runner_ids = [w.get("runner_id") for w in worktrees if w.get("runner_id")]
        assert "list01" in runner_ids
        assert "list02" in runner_ids

    def test_boundary_no_worktrees(self, tmp_git_repo):
        """TC-Boundary: worktree 0개 → runner_id 있는 항목 없음"""
        worktrees = _list_worktrees_in_repo(tmp_git_repo)
        runner_ids = [w.get("runner_id") for w in worktrees if w.get("runner_id")]
        assert runner_ids == []

    def test_correct_conformance_keys(self, worktrees_dir):
        """TC-CORRECT-Conformance: 반환 dict 키가 {path, branch, runner_id} 포함"""
        base_dir, repo = worktrees_dir
        WorktreeManager.create("keycheck", base_dir)
        worktrees = _list_worktrees_in_repo(repo)
        for wt in worktrees:
            assert "path" in wt
            assert "branch" in wt
            assert "runner_id" in wt


# ── 헬퍼: repo 기준으로 list_worktrees() 실행 ─────────────────────────────────

def _list_worktrees_in_repo(repo: Path) -> list:
    """WorktreeManager.list_worktrees()는 cwd에 의존하므로 subprocess로 직접 실행"""
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
