"""
SystemService.restart_worker / stop_watchdogs chat_executor 포함 여부 검증

RIGHT-BICEP + CORRECT 기반 테스트 케이스
패턴: MANAGED_PROJECTS patch + AsyncMock(_kill_pid_file)
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.system.services.worker_service import WorkerService as SystemService


# ---------------------------------------------------------------------------
# 공통 fake config (chat_executor 포함)
# ---------------------------------------------------------------------------

FAKE_PROJECTS_WITH_CHAT = {
    "monitor-page": {
        "path": "D:\\dummy\\path",
        "workers": {
            "pid_dir": ".pids",
            "items": [
                {
                    "name": "unified_worker",
                    "label": "통합 워커",
                    "tier": "worker",
                    "watchdog_pid_file": "worker_watchdog_admin.pid",
                    "worker_pid_file": "unified_worker_admin.pid",
                },
                {
                    "name": "claude_worker",
                    "label": "Claude 워커",
                    "tier": "worker",
                    "watchdog_pid_file": "claude_watchdog_admin.pid",
                    "worker_pid_file": "claude_worker_admin.pid",
                },
                {
                    "name": "command_listener",
                    "label": "명령 리스너",
                    "tier": "infra",
                    "watchdog_pid_file": "command_listener_watchdog_admin.pid",
                    "worker_pid_file": "command_listener_admin.pid",
                },
                {
                    "name": "api_watchdog",
                    "label": "API 왓치독",
                    "tier": "infra",
                    "watchdog_pid_file": "api_watchdog_admin.pid",
                    "worker_pid_file": None,
                },
                {
                    "name": "chat_executor",
                    "label": "Chat Executor",
                    "tier": "worker",
                    "watchdog_pid_file": "chat_executor_watchdog_admin.pid",
                    "worker_pid_file": "chat_executor_admin.pid",
                },
            ],
        },
    }
}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# TC T1-6a: restart_worker("all") — chat_executor 포함 여부 (CARDINALITY)
# ---------------------------------------------------------------------------


def test_restart_worker_all_Ca_includes_chat_executor():
    """Ca: restart_worker('all') 실행 시 chat_executor가 kill 대상에 포함되는지 검증"""
    svc = SystemService()
    kill_calls = []

    async def fake_kill(pid_path, label):
        kill_calls.append(str(pid_path))
        return (True, f"{label} 종료됨")

    with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", FAKE_PROJECTS_WITH_CHAT), \
         patch.object(svc, "_kill_pid_file", side_effect=fake_kill):
        result = _run(svc.restart_worker("all"))

    # chat_executor worker PID 파일이 kill 대상으로 포함됐는지 확인
    assert any("chat_executor_admin.pid" in path for path in kill_calls), (
        f"chat_executor_admin.pid가 kill 대상에 없음. 실제 kill 대상: {kill_calls}"
    )
    assert result["success"] is True


def test_restart_worker_all_Ca_excludes_infra_workers():
    """Ca: restart_worker('all')에서 infra tier(command_listener, api_watchdog)는 제외되는지 검증"""
    svc = SystemService()
    kill_calls = []

    async def fake_kill(pid_path, label):
        kill_calls.append(str(pid_path))
        return (True, f"{label} 종료됨")

    with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", FAKE_PROJECTS_WITH_CHAT), \
         patch.object(svc, "_kill_pid_file", side_effect=fake_kill):
        _run(svc.restart_worker("all"))

    infra_pids = ["command_listener_admin.pid", "api_watchdog_admin.pid"]
    for pid in infra_pids:
        assert not any(pid in path for path in kill_calls), (
            f"infra pid {pid}가 kill 대상에 포함됨 (제외되어야 함). 실제: {kill_calls}"
        )


# ---------------------------------------------------------------------------
# TC T1-6b: stop_watchdogs() — chat_executor watchdog 포함 여부 (CARDINALITY)
# ---------------------------------------------------------------------------


def test_stop_watchdogs_Ca_includes_chat_executor_watchdog():
    """Ca: stop_watchdogs() 실행 시 chat_executor_watchdog_admin.pid가 kill 대상에 포함되는지 검증"""
    svc = SystemService()
    kill_calls = []

    async def fake_kill(pid_path, label):
        kill_calls.append(str(pid_path))
        return (True, f"{label} 종료됨")

    with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", FAKE_PROJECTS_WITH_CHAT), \
         patch.object(svc, "_kill_pid_file", side_effect=fake_kill):
        result = _run(svc.stop_watchdogs())

    assert any("chat_executor_watchdog_admin.pid" in path for path in kill_calls), (
        f"chat_executor_watchdog_admin.pid가 kill 대상에 없음. 실제 kill 대상: {kill_calls}"
    )


def test_stop_watchdogs_Ca_includes_chat_executor_worker_pid():
    """Ca: stop_watchdogs() 실행 시 chat_executor worker PID도 함께 kill되는지 검증"""
    svc = SystemService()
    kill_calls = []

    async def fake_kill(pid_path, label):
        kill_calls.append(str(pid_path))
        return (True, f"{label} 종료됨")

    with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", FAKE_PROJECTS_WITH_CHAT), \
         patch.object(svc, "_kill_pid_file", side_effect=fake_kill):
        _run(svc.stop_watchdogs())

    # stop_watchdogs는 watchdog PID + worker PID 모두 kill
    assert any("chat_executor_admin.pid" in path for path in kill_calls), (
        f"chat_executor_admin.pid (worker)가 stop_watchdogs에서 kill 대상에 없음. 실제: {kill_calls}"
    )


def test_stop_watchdogs_Ca_excludes_infra_tier():
    """Ca: stop_watchdogs()에서 infra tier watchdog(command_listener, api_watchdog)는 제외되는지 검증"""
    svc = SystemService()
    kill_calls = []

    async def fake_kill(pid_path, label):
        kill_calls.append(str(pid_path))
        return (True, f"{label} 종료됨")

    with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", FAKE_PROJECTS_WITH_CHAT), \
         patch.object(svc, "_kill_pid_file", side_effect=fake_kill):
        _run(svc.stop_watchdogs())

    infra_watchdog_pids = [
        "command_listener_watchdog_admin.pid",
        "api_watchdog_admin.pid",
    ]
    for pid in infra_watchdog_pids:
        assert not any(pid in path for path in kill_calls), (
            f"infra watchdog {pid}가 stop_watchdogs에 포함됨 (제외되어야 함). 실제: {kill_calls}"
        )


# ---------------------------------------------------------------------------
# Phase T5 HTTP 통합 테스트 — /merge-test에서 실행
# ---------------------------------------------------------------------------
# 아래 테스트는 실행 중인 API 서버가 필요하므로 워크트리에서 실행하지 않는다.
# /merge-test (main 머지 후) 실행 대상이다.
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="T5: HTTP 통합테스트 — /merge-test에서 main 머지 후 실행")
def test_T5_get_workers_includes_chat_executor():
    """T5: GET /api/v1/system/services/workers 응답에 chat_executor 항목이 포함되는지 검증"""
    import httpx
    resp = httpx.get("http://localhost:8001/api/v1/system/services/workers", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    names = [w["name"] for w in data]
    assert "chat_executor" in names, f"chat_executor가 응답에 없음. 항목: {names}"


@pytest.mark.skip(reason="T5: HTTP 통합테스트 — /merge-test에서 main 머지 후 실행")
def test_T5_post_restart_chat_executor_returns_200():
    """T5: POST /api/v1/system/services/workers/chat_executor/restart → 200 반환 검증"""
    import httpx
    resp = httpx.post(
        "http://localhost:8001/api/v1/system/services/workers/chat_executor/restart",
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
