"""WorktreeManager E2E 테스트 — 실제 git 조작"""
import subprocess
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from worktree_manager import WorktreeManager, MergeResult


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
def worktrees_base(tmp_git_repo):
    base = tmp_git_repo / ".worktrees"
    base.mkdir(exist_ok=True)
    return base, tmp_git_repo


class TestWorktreeE2E:
    def test_e2e_1_full_lifecycle(self, worktrees_base):
        """E2E-1: create → 파일 수정 → 커밋 → merge_to_main → main에서 변경 확인 → remove"""
        base_dir, repo = worktrees_base

        # 1. create
        wt_path, _branch = WorktreeManager.create("e2e001", base_dir)
        assert wt_path.is_dir()

        # 2. 파일 수정
        (wt_path / "feature.py").write_text("FEATURE = True")
        subprocess.run(["git", "add", "-A"], cwd=str(wt_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: e2e feature"], cwd=str(wt_path), capture_output=True)

        # 3. merge_to_main
        result = WorktreeManager.merge_to_main("e2e001", base_dir, repo)
        assert result.success is True

        # 4. main에서 변경 확인
        assert (repo / "feature.py").exists()
        assert (repo / "feature.py").read_text() == "FEATURE = True"

        # 5. remove
        WorktreeManager.remove("e2e001", base_dir)
        assert not (base_dir / "e2e001").exists()

    def test_e2e_2_two_worktrees_sequential_merge(self, worktrees_base):
        """E2E-2: 2개 worktree 동시 생성 → 각각 다른 파일 수정 → 순차 머지"""
        base_dir, repo = worktrees_base

        # 2개 worktree 생성
        wt1, _b1 = WorktreeManager.create("e2e_a", base_dir)
        wt2, _b2 = WorktreeManager.create("e2e_b", base_dir)

        # 각각 다른 파일 수정
        (wt1 / "file_a.py").write_text("A = 1")
        subprocess.run(["git", "add", "-A"], cwd=str(wt1), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: A"], cwd=str(wt1), capture_output=True)

        (wt2 / "file_b.py").write_text("B = 2")
        subprocess.run(["git", "add", "-A"], cwd=str(wt2), capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: B"], cwd=str(wt2), capture_output=True)

        # 순차 머지
        r1 = WorktreeManager.merge_to_main("e2e_a", base_dir, repo)
        assert r1.success is True
        r2 = WorktreeManager.merge_to_main("e2e_b", base_dir, repo)
        assert r2.success is True

        # 두 변경 모두 main에 반영
        assert (repo / "file_a.py").exists()
        assert (repo / "file_b.py").exists()

    def test_e2e_3_conflict_on_second_merge(self, worktrees_base):
        """E2E-3: 동일 파일 수정 → 첫 번째 머지 성공, 두 번째 충돌 확인"""
        base_dir, repo = worktrees_base

        wt1, _b1 = WorktreeManager.create("e2e_c1", base_dir)
        wt2, _b2 = WorktreeManager.create("e2e_c2", base_dir)

        # 두 worktree에서 같은 파일 다르게 수정
        (wt1 / "shared.py").write_text("value = 'from_wt1'")
        subprocess.run(["git", "add", "-A"], cwd=str(wt1), capture_output=True)
        subprocess.run(["git", "commit", "-m", "wt1"], cwd=str(wt1), capture_output=True)

        (wt2 / "shared.py").write_text("value = 'from_wt2'")
        subprocess.run(["git", "add", "-A"], cwd=str(wt2), capture_output=True)
        subprocess.run(["git", "commit", "-m", "wt2"], cwd=str(wt2), capture_output=True)

        # 첫 번째 머지 성공
        r1 = WorktreeManager.merge_to_main("e2e_c1", base_dir, repo)
        assert r1.success is True

        # main에서 같은 파일 수정하여 충돌 유도
        subprocess.run(["git", "checkout", "main"], cwd=str(repo), capture_output=True)
        (repo / "shared.py").write_text("value = 'main_modified'")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "main: modify shared"], cwd=str(repo), capture_output=True)

        # 두 번째 머지 충돌
        r2 = WorktreeManager.merge_to_main("e2e_c2", base_dir, repo)
        assert r2.success is False
        assert r2.conflict is True

    def test_e2e_4_remove_cleans_directory_and_branch(self, worktrees_base):
        """E2E-4: remove 후 디렉토리 + 브랜치 완전 삭제 확인"""
        base_dir, repo = worktrees_base

        WorktreeManager.create("e2e_rm", base_dir)
        wt_path = base_dir / "e2e_rm"
        assert wt_path.is_dir()

        # 브랜치 존재 확인
        br = subprocess.run(
            ["git", "branch", "--list", "runner/e2e_rm"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/e2e_rm" in br.stdout

        WorktreeManager.remove("e2e_rm", base_dir)

        # 디렉토리 삭제 확인
        assert not wt_path.exists()

        # 브랜치 삭제 확인
        br_after = subprocess.run(
            ["git", "branch", "--list", "runner/e2e_rm"],
            capture_output=True, text=True, cwd=str(repo)
        )
        assert "runner/e2e_rm" not in br_after.stdout
