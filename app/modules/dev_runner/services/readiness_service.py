"""Dev Runner 시작 전 readiness 요약.

이 서비스는 상태를 변경하지 않고, 이미 노출되는 status/storage-root read model을
사용자-facing 시작 가능성으로 접는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.modules.dev_runner.schemas import (
    DevRunnerReadinessItem,
    DevRunnerReadinessResponse,
    PlanStorageRootStatusResponse,
    RunStatusResponse,
)

_UNSET = object()


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


def _has_configured_engine(config: Mapping[str, Any], engine: str | None) -> bool:
    if not engine:
        return False
    value = config.get(engine)
    if not isinstance(value, Mapping):
        return False
    default_model = value.get("default_model")
    models = value.get("models")
    has_default = isinstance(default_model, str) and bool(default_model.strip())
    has_models = isinstance(models, Mapping) and any(
        isinstance(model, str) and bool(model.strip())
        for model in models.values()
    )
    return has_default or has_models


def _engine_readiness_item(
    engine_config: Mapping[str, Any] | None,
    engine_config_error: str | None,
    default_engine: str | None,
    default_fix_engine: str | None,
) -> DevRunnerReadinessItem:
    if engine_config_error:
        return _item(
            "engine-config",
            "Engine Config",
            "warning",
            "엔진 설정을 읽을 수 없습니다.",
            "시작 전 engines.json과 dev-runner 기본 엔진 설정을 확인하세요.",
        )
    if not engine_config:
        return _item(
            "engine-config",
            "Engine Config",
            "warning",
            "등록된 엔진 설정이 비어 있습니다.",
            "실행 엔진과 phase별 모델 설정을 확인하세요.",
        )

    missing = [
        engine
        for engine in (default_engine, default_fix_engine)
        if engine and not _has_configured_engine(engine_config, engine)
    ]
    if missing:
        return _item(
            "engine-config",
            "Engine Config",
            "warning",
            "기본 엔진 설정에 모델 정보가 없습니다: " + ", ".join(sorted(set(missing))),
            "System AI defaults와 dev-runner engine 설정을 확인하세요.",
        )

    return _item("engine-config", "Engine Config", "info", "기본 엔진 설정 확인됨")


def _quota_readiness_item(
    quota_snapshot: Mapping[str, Any] | None,
    quota_error: str | None,
) -> DevRunnerReadinessItem:
    if quota_error:
        return _item(
            "quota",
            "Quota",
            "warning",
            "quota 상태를 읽을 수 없습니다.",
            "모델 선택기는 실행 시 fallback을 사용할 수 있습니다.",
        )
    if not quota_snapshot:
        return _item(
            "quota",
            "Quota",
            "warning",
            "quota 상태 정보가 비어 있습니다.",
            "quota 기반 모델 선택 정보가 없어도 수동 실행은 가능합니다.",
        )
    return _item("quota", "Quota", "info", "quota snapshot 확인됨")


def build_dev_runner_readiness(
    status: RunStatusResponse,
    storage_roots: PlanStorageRootStatusResponse,
    *,
    engine_config: Mapping[str, Any] | None | object = _UNSET,
    engine_config_error: str | None = None,
    quota_snapshot: Mapping[str, Any] | None | object = _UNSET,
    quota_error: str | None = None,
    default_engine: str | None = None,
    default_fix_engine: str | None = None,
) -> DevRunnerReadinessResponse:
    items: list[DevRunnerReadinessItem] = []

    if status.redis_connected:
        items.append(_item("redis", "Redis", "info", "연결됨"))
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
        items.append(_item("listener", "Listener", "info", "실행 중"))
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

    if status.display_state == "approval_required":
        items.append(
            _item(
                "runner",
                "Runner",
                "blocker",
                status.display_label or "승인 대기 중인 runner가 있습니다.",
                status.display_secondary or "기존 runner의 승인 작업을 먼저 처리하세요.",
            )
        )
    elif status.running:
        items.append(
            _item(
                "runner",
                "Runner",
                "warning",
                "실행 중인 Dev Runner가 있습니다.",
                "동시 실행 여부와 선택한 plan을 확인하세요.",
            )
        )
    else:
        items.append(_item("runner", "Runner", "info", "대기 중"))

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
                "실행 전 plans worktree 변경과 원격 동기화 필요 여부를 확인하세요.",
            )
        )
    else:
        items.append(_item("plan-storage", "Plan Storage", "info", "정상"))

    if engine_config is not _UNSET:
        items.append(
            _engine_readiness_item(
                engine_config if isinstance(engine_config, Mapping) else None,
                engine_config_error,
                default_engine,
                default_fix_engine,
            )
        )

    if quota_snapshot is not _UNSET:
        items.append(
            _quota_readiness_item(
                quota_snapshot if isinstance(quota_snapshot, Mapping) else None,
                quota_error,
            )
        )

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

