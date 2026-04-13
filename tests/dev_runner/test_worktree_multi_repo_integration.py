"""worktree_service 실제 레포 경로 통합 테스트"""

from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(
    not Path("D:/work/project/service/wtools").exists(),
    reason="wtools 레포 없는 환경",
)
async def test_get_all_worktrees_wtools_repo():
    from app.modules.dev_runner.services.worktree_service import get_all_worktrees

    result = await get_all_worktrees(repo_root=Path("D:/work/project/service/wtools"))

    assert hasattr(result, "worktrees")
    assert hasattr(result, "plan_only")
    assert isinstance(result.worktrees, list)
    assert isinstance(result.plan_only, list)
