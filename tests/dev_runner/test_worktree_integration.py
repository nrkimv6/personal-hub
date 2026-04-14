"""워크트리 서비스 통합 TC — 실제 파일시스템 + git 사용 (T3)"""
import pytest
from pathlib import Path

import app.modules.dev_runner.services.worktree_service as svc
from app.modules.dev_runner.schemas import MainDirtyStatus

_REAL_REPO = Path(__file__).parent.parent.parent  # monitor-page 루트


class TestFindPlanFileRealPlanDir:
    def test_find_plan_file_real_plan_dir(self):
        """실제 docs/plan/ 디렉토리에서 find_plan_file 실행 — 타입 확인"""
        result, mtime = svc.find_plan_file("impl/nonexistent-branch-xyz", repo_root=_REAL_REPO)
        # 매칭 없을 때 (None, None) 반환 확인
        assert result is None
        assert mtime is None

    def test_find_plan_file_returns_correct_types(self):
        """find_plan_file은 항상 (Optional[str], Optional[str]) 반환"""
        # 실제 plan 파일에 등록된 브랜치로 호출할 때도 타입 일치
        result = svc.find_plan_file("impl/feat-worktree-tab-enhancements", repo_root=_REAL_REPO)
        assert isinstance(result, tuple)
        assert len(result) == 2
        path, mtime = result
        assert path is None or isinstance(path, str)
        assert mtime is None or isinstance(mtime, str)


class TestGetMainDirtyRealGit:
    @pytest.mark.asyncio
    async def test_get_main_dirty_real_git(self):
        """실제 git repo에서 get_main_dirty 실행 — MainDirtyStatus 타입 + dirty_count >= 0"""
        result = await svc.get_main_dirty(repo_root=_REAL_REPO)
        assert isinstance(result, MainDirtyStatus)
        assert result.dirty_count >= 0
        assert isinstance(result.files, list)
        # dirty_count와 files 길이 일치
        assert result.dirty_count == len(result.files)
