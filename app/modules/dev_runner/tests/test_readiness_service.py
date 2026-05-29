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


def _approval_status() -> RunStatusResponse:
    status = _status()
    status.display_state = "approval_required"
    status.display_label = "서비스 잠금 승인 필요"
    status.display_secondary = "기존 runner의 승인 작업을 처리하세요."
    return status


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


def _engine_config() -> dict:
    return {
        "claude": {"default_model": "sonnet", "models": {"plan": "sonnet", "impl": "sonnet"}},
        "codex": {"default_model": "gpt-5.3-codex", "models": {"impl": "gpt-5.3-codex"}},
    }


def _quota_snapshot() -> dict:
    return {"claude/sonnet": {"weekly_used_pct": 10, "short_cooldown_until": None}}


def test_build_readiness_snapshot_right_all_sources_ok():
    response = build_dev_runner_readiness(
        _status(),
        _roots(_root()),
        engine_config=_engine_config(),
        quota_snapshot=_quota_snapshot(),
        default_engine="claude",
        default_fix_engine="codex",
    )

    assert response.can_start is True
    assert response.severity == "ok"
    assert response.blockers == 0
    assert {item.id for item in response.items} == {
        "redis",
        "listener",
        "runner",
        "plan-storage",
        "engine-config",
        "quota",
    }
    assert all(item.severity == "info" for item in response.items)


def test_build_readiness_snapshot_boundary_missing_optional_quota():
    response = build_dev_runner_readiness(
        _status(),
        _roots(_root()),
        engine_config=_engine_config(),
        quota_snapshot=None,
        default_engine="claude",
        default_fix_engine="codex",
    )

    assert response.can_start is True
    assert response.severity == "warning"
    quota = next(item for item in response.items if item.id == "quota")
    assert quota.severity == "warning"


def test_build_readiness_snapshot_boundary_no_registered_plan_roots():
    response = build_dev_runner_readiness(_status(), _roots())

    assert response.can_start is False
    assert response.severity == "blocker"
    plan_storage = next(item for item in response.items if item.id == "plan-storage")
    assert plan_storage.severity == "blocker"
    assert "등록된 plan storage root" in plan_storage.message


def test_build_readiness_snapshot_error_redis_unavailable():
    response = build_dev_runner_readiness(
        _status(redis_connected=False, listener_alive=False),
        _roots(_root()),
    )

    assert response.can_start is False
    assert response.severity == "blocker"
    assert response.blockers == 2
    assert [item.id for item in response.items if item.severity == "blocker"] == ["redis", "listener"]


def test_build_readiness_snapshot_error_git_status_unreadable():
    response = build_dev_runner_readiness(
        _status(),
        _roots(_root(status="unknown")),
    )

    assert response.can_start is True
    assert response.severity == "warning"
    plan_storage = next(item for item in response.items if item.id == "plan-storage")
    assert plan_storage.severity == "warning"
    assert "Git 상태 수집 오류" in (plan_storage.action or "")


def test_build_readiness_snapshot_conformance_schema():
    response = build_dev_runner_readiness(_status(), _roots(_root()))
    payload = response.model_dump()

    assert {"severity", "items", "blockers", "warnings", "checked_at", "can_start"} <= set(payload)
    assert isinstance(payload["items"], list)
    assert all({"id", "label", "severity", "message", "action"} <= set(item) for item in payload["items"])


def test_build_readiness_snapshot_ordering_latest_blocker_wins():
    response = build_dev_runner_readiness(
        _approval_status(),
        _roots(_root(status="dirty", dirty_count=1)),
        quota_snapshot=None,
    )

    assert response.severity == "blocker"
    assert response.can_start is False
    assert response.blockers == 1
    assert response.warnings == 2
    assert next(item for item in response.items if item.id == "runner").severity == "blocker"


def test_build_readiness_snapshot_reference_no_mutation_action():
    response = build_dev_runner_readiness(
        _status(),
        _roots(_root(status="dirty", dirty_count=2, push_needed=True)),
        engine_config_error="read failed",
        quota_error="read failed",
    )

    action_text = "\n".join(item.action or "" for item in response.items)
    forbidden = ("git pull", "git push", "git merge", "git reset", "git clean", "git checkout", "git restore", "run.ps1", "stop.ps1")
    assert not any(command in action_text.lower() for command in forbidden)


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

