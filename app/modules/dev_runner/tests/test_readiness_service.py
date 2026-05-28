from app.modules.dev_runner.schemas import (
    PlanStorageRootStatusItem,
    PlanStorageRootStatusResponse,
    RunStatusResponse,
)
from app.modules.dev_runner.services.readiness_service import build_dev_runner_readiness
from app.modules.dev_runner.routes.runner import _readiness_storage_roots_timeout_response


def _status(*, redis_connected: bool = True, listener_alive: bool = True) -> RunStatusResponse:
    return RunStatusResponse(
        running=False,
        listener_alive=listener_alive,
        redis_connected=redis_connected,
        pid=None,
        plan_file=None,
        start_time=None,
        current_cycle=None,
        exit_code=None,
        crashed=False,
        current_plan_name=None,
        runner_id=None,
    )


def _roots(*items: PlanStorageRootStatusItem) -> PlanStorageRootStatusResponse:
    return PlanStorageRootStatusResponse(
        checked_at="2026-05-28T10:00:00",
        roots=list(items),
        total=len(items),
        dirty_count=sum(1 for item in items if item.dirty_count > 0),
        push_needed_count=sum(1 for item in items if item.push_needed),
    )


def _root(status: str = "clean", *, exists: bool = True, dirty_count: int = 0, push_needed: bool = False) -> PlanStorageRootStatusItem:
    return PlanStorageRootStatusItem(
        project="monitor-page",
        repo_root="D:/repo",
        worktree_path="D:/repo/.worktrees/plans",
        exists=exists,
        status=status,
        dirty_count=dirty_count,
        checked_at="2026-05-28T10:00:00",
        push_needed=push_needed,
    )


def test_readiness_ok_when_runtime_and_plan_storage_are_ready():
    response = build_dev_runner_readiness(_status(), _roots(_root()))

    assert response.can_start is True
    assert response.severity == "ok"
    assert response.blockers == 0
    assert {item.id for item in response.items} == {"redis", "listener", "plan-storage"}


def test_readiness_blocks_when_redis_or_listener_missing():
    response = build_dev_runner_readiness(
        _status(redis_connected=False, listener_alive=False),
        _roots(_root()),
    )

    assert response.can_start is False
    assert response.severity == "blocker"
    assert response.blockers == 2
    assert [item.id for item in response.items if item.severity == "blocker"] == ["redis", "listener"]


def test_readiness_warns_but_allows_dirty_plan_storage():
    response = build_dev_runner_readiness(
        _status(),
        _roots(_root(status="dirty", dirty_count=2, push_needed=True)),
    )

    assert response.can_start is True
    assert response.severity == "warning"
    assert response.warnings == 1
    plan_storage = next(item for item in response.items if item.id == "plan-storage")
    assert "dirty 1개" in plan_storage.message


def test_readiness_storage_timeout_degrades_to_warning():
    response = build_dev_runner_readiness(
        _status(),
        _readiness_storage_roots_timeout_response(),
    )

    assert response.can_start is True
    assert response.severity == "warning"
    plan_storage = next(item for item in response.items if item.id == "plan-storage")
    assert plan_storage.severity == "warning"
    assert "확정할 수 없습니다" in plan_storage.message

