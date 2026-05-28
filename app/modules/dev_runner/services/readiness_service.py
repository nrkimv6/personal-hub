"""Dev Runner 시작 전 readiness 요약.

이 서비스는 상태를 변경하지 않고, 이미 노출되는 status/storage-root read model을
사용자-facing 시작 가능성으로 접는다.
"""

from __future__ import annotations

from datetime import datetime

from app.modules.dev_runner.schemas import (
    DevRunnerReadinessItem,
    DevRunnerReadinessResponse,
    PlanStorageRootStatusResponse,
    RunStatusResponse,
)


def _item(
    item_id: str,
    label: str,
    severity: str,
    message: str,
    action: str | None = None,
) -> DevRunnerReadinessItem:
    return DevRunnerReadinessItem(
        id=item_id,
        label=label,
        severity=severity,
        message=message,
        action=action,
    )


def build_dev_runner_readiness(
    status: RunStatusResponse,
    storage_roots: PlanStorageRootStatusResponse,
) -> DevRunnerReadinessResponse:
    items: list[DevRunnerReadinessItem] = []

    if status.redis_connected:
        items.append(_item("redis", "Redis", "ok", "연결됨"))
    else:
        items.append(
            _item(
                "redis",
                "Redis",
                "blocker",
                "Dev Runner 상태 저장소에 연결할 수 없습니다.",
                "Redis와 API 서비스를 확인하세요.",
            )
        )

    if status.listener_alive:
        items.append(_item("listener", "Listener", "ok", "실행 중"))
    else:
        items.append(
            _item(
                "listener",
                "Listener",
                "blocker",
                "Dev Runner command listener가 응답하지 않습니다.",
                "worker 서비스를 재시작하거나 listener 상태를 확인하세요.",
            )
        )

    missing_roots = [root for root in storage_roots.roots if root.status == "missing" or not root.exists]
    unknown_roots = [root for root in storage_roots.roots if root.status == "unknown"]
    dirty_roots = [root for root in storage_roots.roots if root.dirty_count > 0]
    sync_needed_roots = [
        root for root in storage_roots.roots
        if root.push_needed or root.ahead > 0 or root.behind > 0
    ]

    if storage_roots.total == 0:
        items.append(
            _item(
                "plan-storage",
                "Plan Storage",
                "blocker",
                "등록된 plan storage root가 없습니다.",
                "Plans 경로 등록 상태를 확인하세요.",
            )
        )
    elif missing_roots:
        items.append(
            _item(
                "plan-storage",
                "Plan Storage",
                "blocker",
                f"{len(missing_roots)}개 plan storage root가 존재하지 않습니다.",
                "Plans storage root 상태를 확인하세요.",
            )
        )
    elif unknown_roots:
        items.append(
            _item(
                "plan-storage",
                "Plan Storage",
                "warning",
                f"{len(unknown_roots)}개 plan storage root 상태를 확정할 수 없습니다.",
                "Git 상태 수집 오류를 확인하세요.",
            )
        )
    elif dirty_roots or sync_needed_roots:
        parts: list[str] = []
        if dirty_roots:
            parts.append(f"dirty {len(dirty_roots)}개")
        if sync_needed_roots:
            parts.append(f"sync 필요 {len(sync_needed_roots)}개")
        items.append(
            _item(
                "plan-storage",
                "Plan Storage",
                "warning",
                "Plan storage root에 " + ", ".join(parts) + " 상태가 있습니다.",
                "실행 전 plans worktree 변경과 push/pull 필요 여부를 확인하세요.",
            )
        )
    else:
        items.append(_item("plan-storage", "Plan Storage", "ok", "정상"))

    blockers = sum(1 for item in items if item.severity == "blocker")
    warnings = sum(1 for item in items if item.severity == "warning")
    severity = "blocker" if blockers else "warning" if warnings else "ok"

    return DevRunnerReadinessResponse(
        checked_at=datetime.now().isoformat(timespec="seconds"),
        severity=severity,
        can_start=blockers == 0,
        items=items,
        blockers=blockers,
        warnings=warnings,
    )

