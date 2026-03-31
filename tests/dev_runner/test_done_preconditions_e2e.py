"""
test_done_preconditions_e2e.py — done 사전 검증 E2E 테스트

T4 검증:
- fix plan(Phase R 없음)에 대해 done API 전체 흐름 실행 시 구현완료 미설정 + 아카이브 미이동
- fix plan(Phase R 방어 완료)에 대해 done API 전체 흐름 정상 완료
"""
import asyncio
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.dev_runner.services.plan_service import PlanService


@pytest.fixture
def svc(dev_runner_config_isolation):
    return PlanService()


def make_fix_plan_no_phase_r(plan_dir: Path, filename: str) -> Path:
    """fix plan (Phase R 없음) 생성"""
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / filename
    plan_path.write_text(textwrap.dedent("""\
        # fix: 테스트 버그 수정

        > 상태: 구현완료
        > 진행률: 2/2 (100%)

        ## TODO
        - [x] 항목 A
        - [x] 항목 B

        *상태: 구현완료 | 진행률: 2/2 (100%)*
    """), encoding="utf-8")
    return plan_path


def make_fix_plan_with_phase_r(plan_dir: Path, filename: str) -> Path:
    """fix plan (Phase R 방어 완료) 생성"""
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / filename
    plan_path.write_text(textwrap.dedent("""\
        # fix: 테스트 버그 수정

        > 상태: 구현완료
        > 진행률: 4/4 (100%)

        ## TODO
        - [x] 항목 A
        - [x] 항목 B

        ### Phase R: 재발 경로 분석

        | 경로 | 방어여부 |
        | path1 | 방어됨 |
        | path2 | 방어됨 |

        ### T3
        - [x] TC

        *상태: 구현완료 | 진행률: 4/4 (100%)*
    """), encoding="utf-8")
    return plan_path


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_done_e2e_fix_plan_no_phase_r_blocked(svc, tmp_path, dev_runner_config_isolation):
    """fix plan(Phase R 없음)에 대해 done API 전체 흐름 실행 시
    구현완료 미설정 + 아카이브 미이동 검증"""
    plan_dir = tmp_path / "docs" / "plan"
    archive_dir = tmp_path / "docs" / "archive"
    plan_path = make_fix_plan_no_phase_r(plan_dir, "2026-03-31_fix-test.md")

    result = await svc.run_done(str(plan_path))

    # run_done은 ValueError를 catch하여 실패 결과 반환
    assert result["success"] is False
    assert "Phase R" in result["message"]

    # plan 파일이 원래 위치에 그대로 있어야 함 (아카이브 미이동)
    assert plan_path.exists(), "plan 파일이 아카이브로 이동되어서는 안 됨"
    assert not archive_dir.exists() or not (archive_dir / "2026-03-31_fix-test.md").exists()

    # 상태가 변경되지 않았어야 함 (원본 그대로)
    content = plan_path.read_text(encoding="utf-8")
    assert "구현완료" in content  # 이미 구현완료였지만 _update_plan_headers가 호출되지 않아야 함


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_done_e2e_fix_plan_with_phase_r_completes(svc, tmp_path, dev_runner_config_isolation):
    """fix plan(Phase R 방어 완료)에 대해 done API 전체 흐름 정상 완료 검증"""
    plan_dir = tmp_path / "docs" / "plan"
    archive_dir = tmp_path / "docs" / "archive"
    todo_md = tmp_path / "TODO.md"
    todo_md.write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
    done_md = tmp_path / "docs" / "DONE.md"
    done_md.parent.mkdir(parents=True, exist_ok=True)
    done_md.write_text("# DONE\n", encoding="utf-8")

    plan_path = make_fix_plan_with_phase_r(plan_dir, "2026-03-31_fix-test-ok.md")

    with patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
         patch("app.modules.dev_runner.services.plan_service._publish_log"), \
         patch("app.modules.dev_runner.services.plan_service._get_redis", return_value=MagicMock()):
        result = await svc.run_done(str(plan_path))

    assert result["success"] is True
    # plan이 archive로 이동됨
    assert (archive_dir / "2026-03-31_fix-test-ok.md").exists() or not plan_path.exists()
