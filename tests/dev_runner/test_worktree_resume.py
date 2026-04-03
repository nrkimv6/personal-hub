"""dev-runner 워크트리 재사용 — 유닛 + E2E 통합 테스트"""
import subprocess
import shutil
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from plan_worktree_helpers import (
    is_plan_in_progress as _is_plan_in_progress,
    parse_plan_worktree_info as _parse_plan_worktree_info,
    write_plan_worktree_info as _write_plan_worktree_info,
    remove_plan_header_fields as _remove_plan_header_fields,
)
from worktree_manager import WorktreeManager, WorktreeError


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def git_repo(tmp_path):
    """임시 git 저장소 생성"""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "Test"], capture_output=True, cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "checkout", "-B", "main"], capture_output=True, cwd=str(tmp_path))
    base = tmp_path / ".worktrees"
    base.mkdir()
    return tmp_path, base


# ── _is_plan_in_progress ─────────────────────────────────────────────────────

class TestIsPlanInProgress:
    def test_right_returns_true(self, tmp_path):
        """R: '> 상태: 구현중' 있는 plan → True"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 구현중\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is True

    def test_right_returns_false(self, tmp_path):
        """R: '> 상태: 완료' 있는 plan → False"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 완료\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_boundary_no_status(self, tmp_path):
        """B: '> 상태:' 줄 없는 plan → False"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n\n## 내용", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_boundary_empty_file(self, tmp_path):
        """B: 빈 파일 → False"""
        p = tmp_path / "plan.md"
        p.write_text("", encoding="utf-8")
        assert _is_plan_in_progress(str(p)) is False

    def test_error_nonexistent(self):
        """E: 존재하지 않는 파일 → False"""
        assert _is_plan_in_progress("/nonexistent/path/plan.md") is False


# ── _parse_plan_worktree_info ─────────────────────────────────────────────────

class TestParsePlanWorktreeInfo:
    def test_right_both_fields(self, tmp_path):
        """R: branch + worktree 둘 다 있음 → (branch, worktree) 반환"""
        p = tmp_path / "plan.md"
        p.write_text(
            "# 제목\n> 상태: 구현중\n> branch: impl/feature-abc\n> worktree: .worktrees/impl-feature-abc\n",
            encoding="utf-8"
        )
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch == "impl/feature-abc"
        assert worktree == ".worktrees/impl-feature-abc"

    def test_right_no_fields(self, tmp_path):
        """R: 필드 없음 → (None, None) 반환"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 미시작\n", encoding="utf-8")
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch is None
        assert worktree is None

    def test_boundary_only_branch(self, tmp_path):
        """B: branch만 있고 worktree 없음 → (branch, None)"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> branch: impl/feature-abc\n", encoding="utf-8")
        branch, worktree = _parse_plan_worktree_info(str(p))
        assert branch == "impl/feature-abc"
        assert worktree is None

    def test_error_nonexistent(self):
        """E: 존재하지 않는 파일 → (None, None)"""
        branch, worktree = _parse_plan_worktree_info("/nonexistent/plan.md")
        assert branch is None
        assert worktree is None


# ── _write_plan_worktree_info ─────────────────────────────────────────────────

class TestWritePlanWorktreeInfo:
    def test_right_inserts_after_status(self, tmp_path):
        """R: 상태 줄 다음에 branch/worktree 삽입"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n> 상태: 구현중\n\n## 내용\n", encoding="utf-8")
        _write_plan_worktree_info(str(p), "impl/feat", ".worktrees/impl-feat")
        content = p.read_text(encoding="utf-8")
        assert "> branch: impl/feat" in content
        assert "> worktree: .worktrees/impl-feat" in content
        # 상태 줄 다음에 삽입됐는지 확인
        lines = content.splitlines()
        status_idx = next(i for i, l in enumerate(lines) if "상태:" in l)
        assert "> branch: impl/feat" in lines[status_idx + 1]

    def test_right_replaces_existing(self, tmp_path):
        """R: 이미 있으면 교체"""
        p = tmp_path / "plan.md"
        p.write_text(
            "# 제목\n> 상태: 구현중\n> branch: impl/old\n> worktree: .worktrees/impl-old\n",
            encoding="utf-8"
        )
        _write_plan_worktree_info(str(p), "impl/new", ".worktrees/impl-new")
        content = p.read_text(encoding="utf-8")
        assert "impl/new" in content
        assert "impl/old" not in content

    def test_boundary_no_status_line(self, tmp_path):
        """B: 상태 줄 없으면 제목(#) 다음에 삽입"""
        p = tmp_path / "plan.md"
        p.write_text("# 제목\n\n## 내용\n", encoding="utf-8")
        _write_plan_worktree_info(str(p), "impl/feat", ".worktrees/impl-feat")
        content = p.read_text(encoding="utf-8")
        assert "> branch: impl/feat" in content


# ── E2E 통합 테스트 ───────────────────────────────────────────────────────────

class TestWorktreeResumeE2E:
    """stop 후 재실행 시 워크트리 재사용 E2E 흐름 (실제 git 연산)"""

    def test_stop_preserves_worktree_when_in_progress(self, git_repo):
        """T3-1: 구현중 plan에서 stop → 워크트리 보존 → 재실행 → 기존 워크트리 재사용 + 커밋 보존"""
        repo, base = git_repo

        # 1) plan 파일 생성 (구현중 상태)
        plan = repo / "docs" / "plan" / "2026-03-03_test-feature.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# 테스트 기능\n> 상태: 구현중\n\n## 내용\n", encoding="utf-8")

        # 2) 워크트리 생성 + plan 헤더에 기록
        wt_path, branch = WorktreeManager.create("runner-01", base, plan_file=str(plan))
        wt_rel = str(wt_path.relative_to(repo)).replace("\\", "/")
        _write_plan_worktree_info(str(plan), branch, wt_rel)

        # 3) 워크트리에서 커밋 추가
        (wt_path / "work.py").write_text("print('done')")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(wt_path))
        subprocess.run(["git", "commit", "-m", "progress commit"], capture_output=True, cwd=str(wt_path))

        # 4) stop 시뮬레이션: plan이 구현중 → 워크트리 보존
        assert _is_plan_in_progress(str(plan)) is True
        # → WorktreeManager.remove()를 호출하지 않음 (보존)
        assert wt_path.is_dir(), "stop 후 워크트리가 보존되어야 한다"

        # 5) 재실행 시뮬레이션: plan 헤더 읽어서 기존 워크트리 재사용
        existing_branch, existing_wt_rel = _parse_plan_worktree_info(str(plan))
        assert existing_branch == branch
        existing_wt_path = repo / existing_wt_rel
        assert existing_wt_path.is_dir(), "재실행 시 기존 워크트리가 존재해야 한다"

        # 6) 기존 커밋이 보존됐는지 확인
        log = subprocess.run(
            ["git", "log", "--oneline"],
            capture_output=True, text=True, cwd=str(existing_wt_path)
        )
        assert "progress commit" in log.stdout, "기존 커밋이 보존되어야 한다"

    def test_deleted_worktree_triggers_new_creation(self, git_repo):
        """T3-2: 워크트리가 수동 삭제된 상태에서 재실행 → 신규 워크트리 생성"""
        repo, base = git_repo

        # 1) plan 파일 + 워크트리 생성
        plan = repo / "docs" / "plan" / "2026-03-03_deleted-wt.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# 삭제 테스트\n> 상태: 구현중\n\n## 내용\n", encoding="utf-8")
        wt_path, branch = WorktreeManager.create("runner-02", base, plan_file=str(plan))
        wt_rel = str(wt_path.relative_to(repo)).replace("\\", "/")
        _write_plan_worktree_info(str(plan), branch, wt_rel)

        # 2) 워크트리 수동 삭제 (사용자가 직접 지운 시나리오)
        shutil.rmtree(str(wt_path))
        subprocess.run(["git", "worktree", "prune"], capture_output=True, cwd=str(repo))
        subprocess.run(["git", "branch", "-D", branch], capture_output=True, cwd=str(repo))

        # 3) 재실행 시뮬레이션: 경로 없음 → 헤더 제거 → 신규 생성
        existing_branch, existing_wt_rel = _parse_plan_worktree_info(str(plan))
        existing_wt_path = repo / existing_wt_rel
        assert not existing_wt_path.is_dir(), "삭제된 워크트리가 없어야 한다"

        # 헤더 제거 후 신규 생성
        _remove_plan_header_fields(str(plan))
        new_wt_path, new_branch = WorktreeManager.create("runner-02", base, plan_file=str(plan))

        assert new_wt_path.is_dir(), "신규 워크트리가 생성되어야 한다"
        assert new_branch == branch, "같은 브랜치명으로 재생성"

        # plan 헤더에 새 정보 없음 (제거됐으므로)
        b, w = _parse_plan_worktree_info(str(plan))
        assert b is None and w is None, "헤더가 제거된 상태여야 한다"

    def test_completed_plan_worktree_gets_removed(self, git_repo):
        """T3-3: 완료 상태 plan에서 stop → 워크트리 정리됨"""
        repo, base = git_repo

        # 1) plan 파일 생성 (완료 상태)
        plan = repo / "docs" / "plan" / "2026-03-03_completed.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("# 완료 테스트\n> 상태: 완료\n\n## 내용\n", encoding="utf-8")

        # 2) 워크트리 생성
        wt_path, branch = WorktreeManager.create("runner-03", base, plan_file=str(plan))

        # 3) stop 시뮬레이션: plan이 완료 상태 → is_plan_in_progress=False → 워크트리 제거
        assert _is_plan_in_progress(str(plan)) is False
        # → WorktreeManager.remove() 호출
        WorktreeManager.remove("runner-03", base, plan_file=str(plan))

        assert not wt_path.is_dir(), "완료 상태 plan의 워크트리는 정리되어야 한다"
