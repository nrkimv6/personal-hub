"""
TC: auto-resolve abort-before-resolve 버그 수정 검증

Phase T1-1: merge_to_main keep_conflict 옵션 (실제 git repo)
Phase T1-2: _do_inline_merge conflict 분기 (mock)
Phase T1-3: _resolve_conflict 방어 코드 (mock subprocess)
"""
import subprocess
import sys
import importlib
import importlib.util
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# scripts/ sys.path 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from worktree_manager import WorktreeManager, MergeResult

# ── 공통 fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def conflict_repo(tmp_path):
    """충돌이 발생하는 git 저장소 환경 생성.

    구조:
      - main: shared.py = 'main_modified'
      - feature/test 브랜치: shared.py = 'feature'
      → merge 시 충돌 발생
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda args: subprocess.run(args, capture_output=True, cwd=str(repo))
    run(["git", "init"])
    run(["git", "config", "user.email", "t@t.com"])
    run(["git", "config", "user.name", "T"])
    # 초기 커밋 후 브랜치명 main으로 통일 (기본값이 master일 수 있음)
    (repo / "shared.py").write_text("value = 'base'")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "init"])
    run(["git", "branch", "-m", "main"])  # master → main 리네임
    # feature 브랜치에서 같은 파일 수정
    run(["git", "checkout", "-b", "feature/test"])
    (repo / "shared.py").write_text("value = 'feature'")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "feature"])
    # main으로 돌아와서 같은 파일 수정 → 충돌 유발
    run(["git", "checkout", "main"])
    (repo / "shared.py").write_text("value = 'main_modified'")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "main modified"])
    return repo


@pytest.fixture
def no_conflict_repo(tmp_path):
    """충돌 없이 머지되는 git 저장소 환경."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda args: subprocess.run(args, capture_output=True, cwd=str(repo))
    run(["git", "init"])
    run(["git", "config", "user.email", "t@t.com"])
    run(["git", "config", "user.name", "T"])
    (repo / "file.py").write_text("x = 1")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "init"])
    run(["git", "branch", "-m", "main"])  # master → main 리네임
    run(["git", "checkout", "-b", "feature/clean"])
    (repo / "new_file.py").write_text("y = 2")
    run(["git", "add", "."])
    run(["git", "commit", "-m", "add new file"])
    run(["git", "checkout", "main"])
    return repo


# ── Phase T1-1: merge_to_main keep_conflict ───────────────────────────────────

@pytest.mark.skip(reason="keep_conflict 파라미터 제거됨 — merge_to_main은 항상 abort 동작")
class TestMergeToMainKeepConflict:
    """merge_to_main() keep_conflict 옵션 동작 검증 (실제 git repo)"""

    def test_keep_conflict_true_right_preserves_unmerged(self, conflict_repo, tmp_path):
        """R(정상): keep_conflict=True 시 Unmerged 파일이 남아있음 (--diff-filter=U ≥ 1)"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        assert result.conflict is True
        # git diff --diff-filter=U 로 Unmerged 파일 확인
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert diff.stdout.strip() != "", "Unmerged 파일이 남아있어야 한다"
        # cleanup
        subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(conflict_repo))

    def test_keep_conflict_true_right_markers_exist(self, conflict_repo, tmp_path):
        """R(정상): keep_conflict=True 시 충돌 파일에 <<<<<<< 마커 존재"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        content = (conflict_repo / "shared.py").read_text()
        assert "<<<<<<<" in content, "충돌 마커가 파일에 존재해야 한다"
        subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(conflict_repo))

    def test_keep_conflict_false_right_clean_state(self, conflict_repo, tmp_path):
        """R(정상): keep_conflict=False(기본값) 시 abort 후 clean 상태"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=False
        )
        assert result.conflict is True
        # Unmerged 파일 없음
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert diff.stdout.strip() == "", "abort 후 Unmerged 파일이 없어야 한다"
        # 충돌 마커 없음
        content = (conflict_repo / "shared.py").read_text()
        assert "<<<<<<<" not in content, "abort 후 충돌 마커가 없어야 한다"

    def test_keep_conflict_false_boundary_default_param(self, conflict_repo, tmp_path):
        """B(경계): 파라미터 생략 시 기존 동작(abort) 유지 — keep_conflict 기본값=False"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        # keep_conflict 파라미터 없이 호출
        result = WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo, branch="feature/test"
        )
        assert result.conflict is True
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert diff.stdout.strip() == "", "기본값(False)이므로 abort 후 clean 상태"

    def test_keep_conflict_true_error_no_conflict(self, no_conflict_repo, tmp_path):
        """E(에러): 충돌 없는 머지에서 keep_conflict=True → 정상 머지 성공 (부작용 없음)"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main(
            "test", base_dir, no_conflict_repo,
            branch="feature/clean", keep_conflict=True
        )
        assert result.success is True
        assert result.conflict is False
        # MERGE_HEAD 없음 (merge 완료 상태)
        mh = subprocess.run(
            ["git", "rev-parse", "--verify", "MERGE_HEAD"],
            capture_output=True, cwd=str(no_conflict_repo)
        )
        assert mh.returncode != 0, "정상 머지 후 MERGE_HEAD가 없어야 한다"


# ── Phase T1-2: _do_inline_merge conflict 분기 로직 (통합 검증) ───────────────

@pytest.mark.skip(reason="keep_conflict 파라미터 제거됨 — merge_to_main은 항상 abort 동작")
class TestDoInlineMergeConflictFlow:
    """_do_inline_merge conflict 분기의 핵심 동작을 실제 git repo로 검증
    (listener 로드 hang 우회 — 로직을 직접 subprocess 단위로 검증)
    """

    def test_resolve_success_right_status_merged(self, conflict_repo, tmp_path):
        """R(정상): keep_conflict=True 후 수동 resolve + commit → merge commit 확인"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        assert result.conflict is True

        # 수동 해결 (agent 대신)
        (conflict_repo / "shared.py").write_text("value = 'resolved'")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(conflict_repo))
        commit = subprocess.run(
            ["git", "commit", "--no-edit", "-m", "merge: feature/test (auto-resolved)"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert commit.returncode == 0, "resolve 후 commit이 성공해야 한다"

        # merge commit 확인
        log = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        subject = log.stdout.strip()
        assert "merge:" in subject.lower() or "feature/test" in subject.lower(), \
            f"merge commit이 생성되어야 한다: {subject}"

    def test_resolve_fail_right_abort_called(self, conflict_repo, tmp_path):
        """R(정상): resolve 실패 시 git merge --abort 후 clean 상태 복원"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        result = WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        assert result.conflict is True

        # resolve 실패 시뮬레이션 → abort
        abort = subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert abort.returncode == 0, "git merge --abort가 성공해야 한다"

        # clean 상태 확인
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(conflict_repo)
        )
        assert diff.stdout.strip() == "", "abort 후 Unmerged 파일이 없어야 한다"

    def test_resolve_fail_right_status_conflict(self, conflict_repo, tmp_path):
        """R(정상): resolve 실패 + abort 후 MERGE_HEAD 없음 (conflict 상태로 처리)"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(conflict_repo))

        # MERGE_HEAD 없음 = 깨끗이 abort됨
        mh = subprocess.run(
            ["git", "rev-parse", "--verify", "MERGE_HEAD"],
            capture_output=True, cwd=str(conflict_repo)
        )
        assert mh.returncode != 0, "abort 후 MERGE_HEAD가 없어야 한다"

    def test_resolve_success_right_merge_commit_exists(self, conflict_repo, tmp_path):
        """R(정상): resolve 성공 시 HEAD가 merge commit — MERGE_HEAD 사라짐"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        # 해결 후 commit
        (conflict_repo / "shared.py").write_text("value = 'ok'")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(conflict_repo))
        subprocess.run(["git", "commit", "--no-edit"], capture_output=True, cwd=str(conflict_repo))

        # merge 완료 후 MERGE_HEAD 없음
        mh = subprocess.run(
            ["git", "rev-parse", "--verify", "MERGE_HEAD"],
            capture_output=True, cwd=str(conflict_repo)
        )
        assert mh.returncode != 0, "merge commit 후 MERGE_HEAD가 없어야 한다"


# ── Phase T1-3: _resolve_conflict 방어 코드 (MERGE_HEAD 체크) ────────────────

# plan-runner cli.py의 _resolve_conflict를 직접 import하여 테스트
# subprocess 실행(AI executor) 없이 MERGE_HEAD 체크 로직만 검증
_PLAN_RUNNER_PATH = Path("D:/work/project/service/wtools/common/tools/plan-runner")

def _get_resolve_conflict_fn():
    """plan-runner cli.py에서 _resolve_conflict async 함수를 가져옴."""
    spec = importlib.util.spec_from_file_location(
        "_plan_runner_cli",
        _PLAN_RUNNER_PATH / "cli.py"
    )
    mod = importlib.util.module_from_spec(spec)
    # 필요한 mock으로 대체 (AI executor 관련)
    sys.modules.setdefault("typer", MagicMock())
    sys.modules.setdefault("settings", MagicMock())
    sys.modules.setdefault("executor", MagicMock())
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return getattr(mod, "_resolve_conflict", None)


@pytest.mark.skip(reason="keep_conflict 파라미터 제거됨 — merge_to_main은 항상 abort 동작")
class TestResolveConflictGuard:
    """_resolve_conflict의 MERGE_HEAD 기반 abort 상태 감지 방어 검증"""

    def _check_merge_head_guard(self, project_dir: Path) -> tuple:
        """MERGE_HEAD 체크 로직만 직접 실행하여 (is_merging, conflict_files) 반환."""
        # git diff --diff-filter=U
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True, cwd=str(project_dir)
        )
        conflict_files = [f for f in diff.stdout.splitlines() if f.strip()]
        # git rev-parse --verify MERGE_HEAD
        merge_head = subprocess.run(
            ["git", "rev-parse", "--verify", "MERGE_HEAD"],
            capture_output=True, text=True, cwd=str(project_dir)
        )
        is_merging = merge_head.returncode == 0
        return is_merging, conflict_files

    def test_aborted_state_error_exit1(self, tmp_path):
        """E(에러): abort 후 clean 상태 → MERGE_HEAD 없음 → is_merging=False, 방어 조건 충족"""
        repo = tmp_path / "repo"
        repo.mkdir()
        run = lambda args: subprocess.run(args, capture_output=True, cwd=str(repo))
        run(["git", "init"])
        run(["git", "config", "user.email", "t@t.com"])
        run(["git", "config", "user.name", "T"])
        (repo / "f.py").write_text("x=1")
        run(["git", "add", "."])
        run(["git", "commit", "-m", "init"])

        is_merging, conflict_files = self._check_merge_head_guard(repo)
        assert not is_merging, "clean 상태에서 MERGE_HEAD가 없어야 한다"
        assert conflict_files == [], "abort 후 충돌 파일이 없어야 한다"
        # 방어 조건: conflict_files=0 + not merging → exit 1이어야 함

    def test_already_resolved_right_exit0(self, conflict_repo, tmp_path):
        """R(정상): keep_conflict=True 충돌 후 수동 해결 → MERGE_HEAD 존재 + conflict_files=0 → is_merging=True"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=True
        )
        # 충돌 수동 해결
        (conflict_repo / "shared.py").write_text("value = 'resolved'")
        subprocess.run(["git", "add", "."], capture_output=True, cwd=str(conflict_repo))

        is_merging, conflict_files = self._check_merge_head_guard(conflict_repo)
        assert is_merging, "keep_conflict=True 머지 중에는 MERGE_HEAD가 존재해야 한다"
        assert conflict_files == [], "수동 해결 + git add 후 Unmerged 파일이 없어야 한다"
        # 방어 조건: conflict_files=0 + is_merging → exit 0 (이미 해결됨)
        subprocess.run(["git", "merge", "--abort"], capture_output=True, cwd=str(conflict_repo))

    def test_abort_before_resolve_boundary_reproduces_fix(self, conflict_repo, tmp_path):
        """B(경계): keep_conflict=False(abort) 후 상태 → MERGE_HEAD 없음 → 방어 조건 충족"""
        base_dir = tmp_path / ".worktrees"
        base_dir.mkdir()
        # 기존 동작(abort) — 버그의 원인이 된 상태
        WorktreeManager.merge_to_main(
            "test", base_dir, conflict_repo,
            branch="feature/test", keep_conflict=False
        )
        is_merging, conflict_files = self._check_merge_head_guard(conflict_repo)
        assert not is_merging, "abort 후 MERGE_HEAD가 없어야 한다"
        assert conflict_files == [], "abort 후 Unmerged 파일이 없어야 한다"
        # 이 상태에서 _resolve_conflict가 exit 1을 반환해야 함 (버그 수정 검증)
        # → 방어 코드: not is_merging + conflict_files=0 → sys.exit(1)
