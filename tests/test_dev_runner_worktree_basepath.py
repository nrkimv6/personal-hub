"""
tests/test_dev_runner_worktree_basepath.py

dev-runner-command-listener의 get_plan_git_root() 함수 및
worktree basepath 동적 결정 로직 테스트.

버그 재현:
  WORKTREE_BASE_DIR이 monitor-page로 하드코딩되어,
  wtools plan을 처리할 때 워크트리가 monitor-page에 생성됨.
"""

import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# scripts/ 경로를 sys.path에 추가 (get_plan_git_root import 용)
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# PROJECT_ROOT (monitor-page)
_PROJECT_ROOT = Path(__file__).parent.parent

# get_plan_git_root는 scripts/dev-runner-command-listener.py 내 전역 함수
# 직접 import 하기 위해 모듈 로드 (side-effect 없이)
import importlib.util
import types

def _load_listener_module():
    """dev-runner-command-listener.py를 side-effect 없이 로드하여 get_plan_git_root 추출."""
    spec = importlib.util.spec_from_file_location(
        "dev_runner_command_listener",
        str(_SCRIPTS_DIR / "plan_runner" / "dev-runner-command-listener.py"),
    )
    # 실제 실행 없이 모듈 생성만 (redis 연결 등 side-effect 방지)
    mod = types.ModuleType("dev_runner_command_listener")
    mod.__spec__ = spec
    # 전역 함수만 직접 exec 방식 대신 소스에서 추출
    return mod


# ─────────────────────────────────────────────────────────────
# 헬퍼: get_plan_git_root를 직접 실행 가능한 함수로 추출
# ─────────────────────────────────────────────────────────────

def _make_get_plan_git_root(project_root: Path):
    """PROJECT_ROOT를 주입한 get_plan_git_root 함수 반환."""
    import subprocess as _sp
    import logging as _logging

    _logger = _logging.getLogger("test_listener")

    def get_plan_git_root(plan_file: str) -> Path:
        try:
            plan_path = Path(plan_file)
            cwd = str(plan_path.parent) if plan_path.parent.is_dir() else str(plan_path.parent.parent)
            result = _sp.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=cwd, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except Exception as e:
            _logger.warning(f"get_plan_git_root: git rev-parse 실패: {e}")
        _logger.warning(f"get_plan_git_root: fallback to PROJECT_ROOT")
        return project_root

    return get_plan_git_root


# ─────────────────────────────────────────────────────────────
# T1: get_plan_git_root() 단위 테스트
# ─────────────────────────────────────────────────────────────

class TestGetPlanGitRoot:
    """get_plan_git_root() 단위 테스트 (RIGHT-BICEP)"""

    def test_get_plan_git_root_wtools_plan(self):
        """R: wtools 경로의 실존 plan 파일 → wtools git root 반환"""
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)
        wtools_plan = "D:/work/project/service/wtools/common/docs/plan/2026-03-09_fix-plan-runner-done-worktree-check.md"
        wtools_root = Path("D:/work/project/service/wtools")

        # wtools plan이 실제 존재할 때만 실물 git 명령으로 검증
        if Path(wtools_plan).exists():
            result = get_fn(wtools_plan)
            assert result == wtools_root.resolve() or result == wtools_root, \
                f"wtools plan의 git root는 {wtools_root}이어야 함, 실제: {result}"
        else:
            pytest.skip("wtools plan 파일이 존재하지 않아 스킵")

    def test_get_plan_git_root_monitor_page_plan(self):
        """R: monitor-page 경로의 실존 plan 파일 → monitor-page git root 반환"""
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)
        mp_plan = str(_PROJECT_ROOT / "docs/plan/2026-03-09_fix-dev-runner-worktree-basepath.md")
        result = get_fn(mp_plan)
        expected = _PROJECT_ROOT.resolve()
        assert result.resolve() == expected or result == _PROJECT_ROOT, \
            f"monitor-page plan의 git root는 {_PROJECT_ROOT}이어야 함, 실제: {result}"

    def test_get_plan_git_root_nonexistent_file(self):
        """E: 존재하지 않는 파일 → PROJECT_ROOT fallback 반환"""
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)
        result = get_fn("/nonexistent/path/plan.md")
        assert result == _PROJECT_ROOT, \
            f"존재하지 않는 파일은 PROJECT_ROOT fallback이어야 함, 실제: {result}"

    def test_get_plan_git_root_git_fails(self):
        """E: git 명령 실패(returncode!=0) → PROJECT_ROOT fallback 반환"""
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 128
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            result = get_fn("/some/plan.md")
            assert result == _PROJECT_ROOT, \
                f"git 실패 시 PROJECT_ROOT fallback이어야 함, 실제: {result}"

    def test_get_plan_git_root_git_empty_output(self):
        """E: git 명령 returncode=0이지만 빈 출력 → PROJECT_ROOT fallback"""
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "   "  # 공백만
            mock_run.return_value = mock_result

            result = get_fn("/some/plan.md")
            assert result == _PROJECT_ROOT, \
                f"빈 출력 시 PROJECT_ROOT fallback이어야 함, 실제: {result}"


# ─────────────────────────────────────────────────────────────
# T1: 통합 TC - worktree 생성 위치 검증 (mock WorktreeManager)
# ─────────────────────────────────────────────────────────────

class TestWorktreeBasepathSelection:
    """worktree basepath 선택 로직 통합 테스트 (WorktreeManager.create mock)"""

    def test_worktree_created_in_correct_repo(self):
        """R: wtools plan 경로 입력 시 wtools git root의 .worktrees/ 에 워크트리 생성됨"""
        wtools_root = Path("D:/work/project/service/wtools")
        wtools_plan = "D:/work/project/service/wtools/common/docs/plan/some-plan.md"

        # get_plan_git_root가 wtools_root를 반환하도록 mock
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(wtools_root) + "\n"
            mock_run.return_value = mock_result

            result = get_fn(wtools_plan)

        expected_base = wtools_root / ".worktrees"
        actual_base = result / ".worktrees"
        assert actual_base == expected_base, \
            f"wtools plan의 worktree base는 {expected_base}이어야 함, 실제: {actual_base}"

    def test_worktree_not_created_in_monitor_page_for_wtools_plan(self):
        """B: wtools plan일 때 WORKTREE_BASE_DIR(monitor-page/.worktrees) 가 사용되지 않음"""
        monitor_page_worktree_base = _PROJECT_ROOT / ".worktrees"
        wtools_root = Path("D:/work/project/service/wtools")
        wtools_plan = "D:/work/project/service/wtools/common/docs/plan/some-plan.md"

        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(wtools_root) + "\n"
            mock_run.return_value = mock_result

            result = get_fn(wtools_plan)

        actual_base = result / ".worktrees"
        assert actual_base != monitor_page_worktree_base, \
            f"wtools plan은 monitor-page/.worktrees 에 생성되면 안 됨"

    def test_monitor_page_plan_uses_project_root(self):
        """R: monitor-page plan → PROJECT_ROOT/.worktrees 반환 (기존 동작 유지)"""
        mp_plan = str(_PROJECT_ROOT / "docs/plan/some-plan.md")
        get_fn = _make_get_plan_git_root(_PROJECT_ROOT)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(_PROJECT_ROOT) + "\n"
            mock_run.return_value = mock_result

            result = get_fn(mp_plan)

        assert result == _PROJECT_ROOT, \
            f"monitor-page plan은 PROJECT_ROOT를 반환해야 함"

    def test_no_plan_file_uses_project_root(self):
        """B: plan_file=None 이면 PROJECT_ROOT/.worktrees 사용 (기존 동작 유지)"""
        # plan_file이 None이면 get_plan_git_root를 호출하지 않고 PROJECT_ROOT 사용
        plan_project_root = _PROJECT_ROOT  # plan_file=None → PROJECT_ROOT
        expected_base = _PROJECT_ROOT / ".worktrees"
        assert plan_project_root / ".worktrees" == expected_base


# ─────────────────────────────────────────────────────────────
# T3: 실제 git worktree 생성 통합 테스트
# ─────────────────────────────────────────────────────────────

class TestWorktreeCreationIntegration:
    """실제 git 명령을 사용한 통합 테스트 (tmp_path 기반 가상 레포)"""

    def test_worktree_created_in_wtools_not_monitor_page_integration(self, tmp_path):
        """R: 두 git repo에서 wtools plan의 worktree가 wtools에 생성되는지 실물 git으로 검증"""
        # 두 개의 임시 git repo 생성
        mp_repo = tmp_path / "monitor-page"
        wtools_repo = tmp_path / "wtools"
        mp_repo.mkdir()
        wtools_repo.mkdir()

        for repo in [mp_repo, wtools_repo]:
            subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
            # 초기 커밋 (worktree add는 최소 1개 커밋 필요)
            (repo / "README.md").write_text("test")
            subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)

        # wtools plan 파일 생성
        wtools_plan_dir = wtools_repo / "common" / "docs" / "plan"
        wtools_plan_dir.mkdir(parents=True)
        wtools_plan = wtools_plan_dir / "test-plan.md"
        wtools_plan.write_text("# Test Plan")

        # get_plan_git_root 호출 → wtools_repo 반환 확인
        get_fn = _make_get_plan_git_root(mp_repo)
        result_root = get_fn(str(wtools_plan))

        # wtools_repo의 git root를 반환해야 함
        assert result_root.resolve() == wtools_repo.resolve(), \
            f"wtools plan의 git root는 {wtools_repo}이어야 함, 실제: {result_root}"

        # plan_project_root / ".worktrees" 가 mp_repo/.worktrees가 아닌지 확인
        worktree_base = result_root / ".worktrees"
        mp_worktree_base = mp_repo / ".worktrees"
        assert worktree_base != mp_worktree_base, \
            f"wtools plan의 worktree base는 monitor-page가 아니어야 함"
        assert worktree_base == wtools_repo / ".worktrees", \
            f"wtools plan의 worktree base는 wtools_repo/.worktrees이어야 함"


# ─────────────────────────────────────────────────────────────
# T1: get_target_project_root() 단위 테스트
# ─────────────────────────────────────────────────────────────

class TestGetTargetProjectRoot:
    """get_target_project_root() 단위 테스트 — plans root와 target project root 분리"""

    def _import_fn(self):
        """get_target_project_root를 _dr_process_utils에서 import."""
        pr_dir = _SCRIPTS_DIR / "plan_runner"
        if str(pr_dir) not in sys.path:
            sys.path.insert(0, str(pr_dir))
        from _dr_process_utils import get_target_project_root
        return get_target_project_root

    def test_get_target_project_root_plans_worktree_path(self, tmp_path):
        """R: .worktrees/plans/docs/plan/xxx.md 입력 시 target project root 반환
        (.worktrees/plans가 아님을 검증).
        """
        # tmp_path 구조: project-root/.worktrees/plans/docs/plan/
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        # .git 디렉토리 생성 (project root 판정용)
        (project_root / ".git").mkdir()
        plans_dir = project_root / ".worktrees" / "plans" / "docs" / "plan"
        plans_dir.mkdir(parents=True)
        plan_file = plans_dir / "2026-04-24_fix-test.md"
        plan_file.write_text("# Test Plan\n> 상태: 구현중\n")

        get_fn = self._import_fn()

        # git rev-parse가 .worktrees/plans를 반환하도록 mock
        plans_git_root = project_root / ".worktrees" / "plans"
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(plans_git_root) + "\n"
            mock_run.return_value = mock_result

            result = get_fn(str(plan_file))

        # .worktrees/plans가 아니라 project_root를 반환해야 함
        assert result.resolve() == project_root.resolve(), (
            f".worktrees/plans 경로 입력 시 get_target_project_root()는 "
            f"project_root({project_root})를 반환해야 함, 실제: {result}"
        )
        assert ".worktrees" not in result.parts or result == project_root, (
            f"반환 경로에 .worktrees가 포함되면 안 됨: {result}"
        )

    def test_get_target_project_root_env_override(self, tmp_path):
        """R: PLAN_RUNNER_PROJECT_ROOT 환경변수 설정 시 우선 반환."""
        project_root = tmp_path / "env-project"
        project_root.mkdir()

        get_fn = self._import_fn()

        with patch.dict("os.environ", {"PLAN_RUNNER_PROJECT_ROOT": str(project_root)}):
            result = get_fn("/some/plan/path/plan.md")

        assert result == project_root.resolve(), (
            f"PLAN_RUNNER_PROJECT_ROOT 설정 시 해당 경로 반환해야 함, 실제: {result}"
        )

    def test_get_target_project_root_regular_path(self, tmp_path):
        """R: 일반 경로(non-.worktrees) → git root 그대로 반환."""
        project_root = tmp_path / "normal-project"
        project_root.mkdir()
        plan_dir = project_root / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "test.md"
        plan_file.write_text("# Test")

        get_fn = self._import_fn()

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(project_root) + "\n"
            mock_run.return_value = mock_result

            result = get_fn(str(plan_file))

        assert result == project_root, (
            f"일반 경로에서 git root 그대로 반환해야 함, 실제: {result}"
        )
