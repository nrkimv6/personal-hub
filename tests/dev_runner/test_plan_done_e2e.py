"""
test_plan_done_e2e.py — monitor-page batch_done API e2e 테스트

검증:
- POST /plans/batch-done 호출 시 완료 plan 아카이브
- 성공 시 PLAN_DONE 로그 태그 확인
- 실패 시 PLAN_FAILED 로그 태그 확인 (로그 버그 수정 검증)
- resolver 실패 경로(done hard-fail)에서 plan 이동이 발생하지 않는지 확인
"""

import asyncio
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.dev_runner.services.plan_service import PlanService


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def svc(dev_runner_config_isolation):
    return PlanService()


def make_completed_plan(plan_dir: Path, filename: str) -> Path:
    """완료된 plan 파일 생성"""
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / filename
    plan_path.write_text(textwrap.dedent("""\
        # 완료 테스트 plan

        > 상태: 구현완료

        - [x] 항목 A
        - [x] 항목 B
    """), encoding="utf-8")
    return plan_path


# =============================================================================
# batch_done — 성공 케이스
# =============================================================================

@pytest.mark.asyncio
async def test_batch_done_success_logs_plan_done(svc, tmp_path, dev_runner_config_isolation):
    """
    batch_done 성공 시 PLAN_DONE 로그 태그 출력

    흐름: run_done 성공 mock → PLAN_DONE 로그 확인
    """
    # 완료 가능한 plan 설정
    plan_dir = tmp_path / "docs" / "plan"
    plan_path = make_completed_plan(plan_dir, "2026-02-24-test.md")

    log_messages = []

    def fake_publish(tag: str, message: str):
        log_messages.append((tag, message))

    with patch(
        "app.modules.dev_runner.services.plan_service._publish_log",
        side_effect=fake_publish
    ), patch.object(
        svc, "list_plans",
        return_value=[MagicMock(
            filename="2026-02-24-test.md",
            status="구현완료",
            file_path=str(plan_path),
        )]
    ), patch.object(
        svc, "_can_done", return_value=True
    ), patch.object(
        svc, "run_done",
        new=AsyncMock(return_value={"success": True, "message": "완료"})
    ):
        result = await svc.batch_done()

    # PLAN_DONE 로그가 기록되었는지 확인
    plan_done_logs = [m for tag, m in log_messages if "PLAN_DONE" in m]
    assert len(plan_done_logs) >= 1, f"PLAN_DONE 로그 없음. 전체 로그: {log_messages}"

    # PLAN_FAILED 로그가 없어야 함
    plan_failed_logs = [m for tag, m in log_messages if "PLAN_FAILED" in m]
    assert len(plan_failed_logs) == 0, f"예상치 못한 PLAN_FAILED 로그: {plan_failed_logs}"


# =============================================================================
# batch_done — 실패 케이스 (로그 버그 수정 검증)
# =============================================================================

@pytest.mark.asyncio
async def test_batch_done_failure_logs_plan_failed_not_plan_done(svc, tmp_path, dev_runner_config_isolation):
    """
    batch_done 실패 시 PLAN_FAILED 로그 태그 출력 (PLAN_DONE 아님)

    로그 버그 수정 검증:
    - 기존: 성공/실패 모두 PLAN_DONE 로깅
    - 수정: 실패 시 PLAN_FAILED 로깅
    """
    plan_dir = tmp_path / "docs" / "plan"
    plan_path = make_completed_plan(plan_dir, "2026-02-24-fail.md")

    log_messages = []

    def fake_publish(tag: str, message: str):
        log_messages.append((tag, message))

    with patch(
        "app.modules.dev_runner.services.plan_service._publish_log",
        side_effect=fake_publish
    ), patch.object(
        svc, "list_plans",
        return_value=[MagicMock(
            filename="2026-02-24-fail.md",
            status="구현완료",
            file_path=str(plan_path),
        )]
    ), patch.object(
        svc, "_can_done", return_value=True
    ), patch.object(
        svc, "run_done",
        new=AsyncMock(return_value={"success": False, "message": "처리 실패"})
    ):
        result = await svc.batch_done()

    # PLAN_FAILED 로그가 기록되었는지 확인 (버그 수정 검증)
    plan_failed_logs = [m for tag, m in log_messages if "PLAN_FAILED" in m]
    assert len(plan_failed_logs) >= 1, f"PLAN_FAILED 로그 없음. 전체 로그: {log_messages}"

    # 실패 시 PLAN_DONE 로그가 없어야 함 (버그 수정 검증)
    plan_done_logs = [m for tag, m in log_messages if "PLAN_DONE" in m]
    assert len(plan_done_logs) == 0, (
        f"실패했는데 PLAN_DONE 로그가 기록됨 (로그 버그 미수정): {plan_done_logs}"
    )


# =============================================================================
# batch_done — 빈 대상
# =============================================================================

@pytest.mark.asyncio
async def test_batch_done_no_targets(svc, dev_runner_config_isolation):
    """완료 가능한 plan이 없으면 결과 0개"""
    with patch.object(svc, "list_plans", return_value=[]), \
         patch.object(svc, "_can_done", return_value=False):
        result = await svc.batch_done()

    assert result.get("total", 0) == 0 or result.get("success_count", 0) == 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_done_resolver_error_keeps_plan_unmoved_E(svc, tmp_path, dev_runner_config_isolation):
    """E: docs/plan 외 경로는 resolver hard-fail로 종료하고 파일 이동을 금지한다."""
    src_dir = tmp_path / "docs" / "tmp"
    src_dir.mkdir(parents=True, exist_ok=True)
    plan_path = src_dir / "2026-04-03_plan-done-resolver-fail.md"
    original = textwrap.dedent("""\
        # feat: resolver fail e2e

        > 상태: 구현완료
        > 진행률: 1/1 (100%)

        - [x] task
    """)
    plan_path.write_text(original, encoding="utf-8")
    archive_path = tmp_path / "docs" / "archive" / plan_path.name

    result = await svc.run_done(str(plan_path))

    assert result["success"] is False
    assert "archive target resolve failed" in result["message"]
    assert plan_path.exists()
    assert plan_path.read_text(encoding="utf-8") == original
    assert not archive_path.exists()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_batch_done_ignores_unrelated_snapshot_json_B(svc, tmp_path, dev_runner_config_isolation):
    """B: unrelated ownership snapshot이 남아 있어도 batch_done(manual path)은 정상 완료된다."""
    plan_dir = tmp_path / "docs" / "plan"
    archive_dir = tmp_path / "docs" / "archive"
    ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
    ownership_dir.mkdir(parents=True, exist_ok=True)
    plan_path = make_completed_plan(plan_dir, "2026-04-21-batch-done-snapshot.md")

    (tmp_path / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
    done_md = tmp_path / "docs" / "DONE.md"
    done_md.parent.mkdir(parents=True, exist_ok=True)
    done_md.write_text("# DONE\n", encoding="utf-8")
    (ownership_dir / "other-runner.json").write_text(
        json.dumps(
            {
                "runner_id": "other-runner",
                "captured_at": "2026-04-21T10:00:00",
                "project_root": str(tmp_path),
                "dirty_files": ["TODO.md"],
                "owned_files": [],
                "clean_at_start_files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    svc.add_path(str(plan_dir))

    with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir), \
         patch.object(svc, "_git_commit", new=AsyncMock(return_value="commit ok")), \
         patch("app.modules.dev_runner.services.plan_service._publish_log"), \
         patch("app.modules.dev_runner.services.plan_service._get_redis", return_value=MagicMock()):
        result = await svc.batch_done()

    assert result["total"] == 1
    assert result["success"] == 1
    assert result["failed"] == 0
    assert not plan_path.exists()
    assert (archive_dir / plan_path.name).exists()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_done_strict_snapshot_failure_keeps_plan_unmoved_E(svc, tmp_path, dev_runner_config_isolation):
    """E: auto-done + snapshot JSON 충돌이면 archive 이동 없이 ownership_guard로 실패한다."""
    plan_dir = tmp_path / "docs" / "plan"
    archive_dir = tmp_path / "docs" / "archive"
    ownership_dir = tmp_path / "logs" / "dev_runner" / "ownership"
    ownership_dir.mkdir(parents=True, exist_ok=True)
    plan_path = make_completed_plan(plan_dir, "2026-04-21-strict-fail.md")
    original = plan_path.read_text(encoding="utf-8")

    (tmp_path / "TODO.md").write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
    done_md = tmp_path / "docs" / "DONE.md"
    done_md.parent.mkdir(parents=True, exist_ok=True)
    done_md.write_text("# DONE\n", encoding="utf-8")
    (ownership_dir / "strict-runner.json").write_text(
        json.dumps(
                {
                    "runner_id": "strict-runner",
                    "captured_at": "2026-04-21T11:00:00",
                    "project_root": str(tmp_path),
                    "dirty_files": [],
                    "owned_files": ["docs/plan/owned-other.md"],
                    "clean_at_start_files": [],
                },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch.object(type(svc), "_ownership_snapshot_dir", return_value=ownership_dir):
        result = await svc.run_done(str(plan_path), runner_id="strict-runner")

    assert result["success"] is False
    assert result["reason"] == "ownership_guard"
    assert plan_path.exists()
    assert plan_path.read_text(encoding="utf-8") == original
    assert not (archive_dir / plan_path.name).exists()


# =============================================================================
# T5: plans-root plan run_done 회귀 TC
# =============================================================================

@pytest.mark.asyncio
async def test_run_done_plans_root_plan_finds_correct_project_dir(tmp_path, svc):
    '''T5/R: .worktrees/plans/docs/plan/xxx.md 경로의 plan이
    preedit_gate_failed 없이 target project DONE을 정상 참조하는 회귀.

    _resolve_project_dir()가 .worktrees/plans를 target project root로 오인하지 않고
    실제 project root(tmp_path)를 반환해야 한다.
    '''
    project_root = tmp_path
    plans_dir = project_root / '.worktrees' / 'plans' / 'docs' / 'plan'
    plans_dir.mkdir(parents=True)

    plan_file = plans_dir / '2026-04-24_fix-plans-root-e2e.md'
    plan_file.write_text(
        '# Fix plans root e2e\n\n'
        '> 상태: 구현완료\n'
        '> 진행률: 1/1 (100%)\n\n'
        '- [x] 항목 A\n\n'
        '*상태: 구현완료 | 진행률: 1/1 (100%)*\n',
        encoding='utf-8',
    )

    # run_done이 _resolve_project_dir를 호출할 때 .worktrees/plans가 아닌
    # project_root를 사용해야 archive 경로가 올바르게 설정됨
    from app.modules.dev_runner.services.plan_done_service import PlanDoneService
    resolved = PlanDoneService._resolve_project_dir(str(plan_file))

    # plans root가 아닌 project root 반환 검증
    assert resolved is not None, '_resolve_project_dir()가 None 반환하면 안 됨'
    plans_root = project_root / '.worktrees' / 'plans'
    assert resolved != plans_root, (
        f'_resolve_project_dir()가 plans root를 반환하면 안 됨 (run_done 회귀): {resolved}'
    )
    assert resolved == project_root, (
        f'_resolve_project_dir()는 project_root({project_root})를 반환해야 함, 실제: {resolved}'
    )
