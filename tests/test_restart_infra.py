"""
restart_infra 단위 테스트 (T1)

SystemService.restart_infra() 및 get_worker_status() tier 필드 검증
"""

import asyncio
import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.system_service import SystemService


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── restart_infra ────────────────────────────────────────────────────────────

class TestRestartInfra:

    def _make_redis_mock(self, result_payload: dict | None):
        """Redis mock: lpush, delete, brpop 지원"""
        mock = AsyncMock()
        mock.ping = AsyncMock(return_value=True)
        mock.delete = AsyncMock()
        mock.lpush = AsyncMock()
        if result_payload is not None:
            raw = json.dumps(result_payload)
            mock.brpop = AsyncMock(return_value=("infra:command_results", raw))
        else:
            mock.brpop = AsyncMock(return_value=None)
        return mock

    def test_restart_infra_sends_redis_command(self):
        """R(정상): restart_infra("api_watchdog") → Redis infra:commands에 restart-infra 명령 LPUSH"""
        redis_mock = self._make_redis_mock({"success": True, "message": "완료"})

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is True
        redis_mock.lpush.assert_called_once()
        call_args = redis_mock.lpush.call_args
        key = call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert key == "infra:commands"
        assert payload["action"] == "restart-infra"
        assert payload["target"] == "api_watchdog"

    def test_restart_infra_command_listener(self):
        """R(정상): restart_infra("command_listener") → restart-listener 액션 전송"""
        redis_mock = self._make_redis_mock({"success": True, "message": "완료"})

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            result = run(svc.restart_infra("command_listener"))

        assert result["success"] is True
        call_args = redis_mock.lpush.call_args
        payload = json.loads(call_args[0][1])
        assert payload["action"] == "restart-listener"
        assert "target" not in payload

    def test_restart_infra_invalid_name(self):
        """E(에러): 존재하지 않는 name → success=False, Redis 호출 없음"""
        svc = SystemService()
        result = run(svc.restart_infra("nonexistent_proc_xyz"))

        assert result["success"] is False
        assert "nonexistent_proc_xyz" in result["message"]

    def test_restart_infra_non_infra_tier(self):
        """B(경계): worker tier name(unified_worker) → infra 필터에 의해 거부"""
        svc = SystemService()
        result = run(svc.restart_infra("unified_worker"))

        assert result["success"] is False

    def test_restart_infra_timeout(self):
        """E(에러): Redis brpop 타임아웃 → success=False, 타임아웃 메시지"""
        redis_mock = self._make_redis_mock(None)  # brpop returns None (timeout)

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "타임아웃" in result["message"]

    def test_restart_infra_redis_unavailable(self):
        """E(에러): Redis 연결 없음 → success=False"""
        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=None)
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "Redis" in result["message"]

    def test_restart_infra_lpush_exception(self):
        """E(에러): lpush 예외 발생 → exception handler가 success=False 반환"""
        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock()
        redis_mock.lpush = AsyncMock(side_effect=RuntimeError("connection broken"))

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            result = run(svc.restart_infra("api_watchdog"))

        assert result["success"] is False
        assert "실패" in result["message"] or "connection broken" in result["message"]

    def test_restart_infra_delete_called_before_lpush(self):
        """O(순서): delete(infra:command_results) → lpush(infra:commands) 순서 검증"""
        call_order = []
        redis_mock = AsyncMock()

        async def track_delete(*a, **kw): call_order.append("delete")
        async def track_lpush(*a, **kw): call_order.append("lpush")

        redis_mock.delete = track_delete
        redis_mock.lpush = track_lpush
        redis_mock.brpop = AsyncMock(return_value=(
            "infra:command_results",
            json.dumps({"success": True, "message": "완료"})
        ))

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            run(svc.restart_infra("api_watchdog"))

        assert call_order == ["delete", "lpush"], f"순서 오류: {call_order}"

    def test_restart_infra_infra_command_listener(self):
        """B(경계): infra_command_listener(watchdog=None) → restart-infra + target 전송"""
        redis_mock = self._make_redis_mock({"success": True, "message": "완료"})

        with patch("app.shared.redis.client.RedisClient") as mock_client:
            mock_client.get_client = AsyncMock(return_value=redis_mock)
            svc = SystemService()
            result = run(svc.restart_infra("infra_command_listener"))

        assert result["success"] is True
        call_args = redis_mock.lpush.call_args
        payload = json.loads(call_args[0][1])
        assert payload["action"] == "restart-infra"
        assert payload["target"] == "infra_command_listener"


# ─── get_worker_status tier 필드 ─────────────────────────────────────────────

class TestGetWorkerStatusTier:

    def test_get_worker_status_includes_tier(self, tmp_path):
        """R(정상): get_worker_status() 반환값의 각 entry에 tier 키 존재"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        # monitor-page path를 tmp_path로 교체 (pid 파일 없음 → running=False, 에러 없음)
        fake["monitor-page"]["path"] = str(tmp_path)
        (tmp_path / ".pids").mkdir(exist_ok=True)

        with patch("app.modules.system.services.system_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            result = asyncio.get_event_loop().run_until_complete(svc.get_worker_status())

        monitor_entries = [e for e in result if e["project"] == "monitor-page"]
        assert len(monitor_entries) > 0
        for entry in monitor_entries:
            assert "tier" in entry
            assert entry["tier"] in ("worker", "infra")

    def test_get_worker_status_default_tier(self, tmp_path):
        """B(경계): config에 tier 미지정 항목 → 기본값 'worker'"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        fake["monitor-page"]["path"] = str(tmp_path)
        (tmp_path / ".pids").mkdir(exist_ok=True)
        # tier 필드 없는 항목 추가
        fake["monitor-page"]["workers"]["items"].append({
            "name": "no_tier_worker",
            "label": "tier 없음",
            # tier 키 없음
            "watchdog_pid_file": None,
            "worker_pid_file": None,
        })

        with patch("app.modules.system.services.system_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            result = asyncio.get_event_loop().run_until_complete(svc.get_worker_status())

        no_tier = next((e for e in result if e["name"] == "no_tier_worker"), None)
        assert no_tier is not None
        assert no_tier["tier"] == "worker"


# ─── restart_worker infra 제외 ────────────────────────────────────────────────

class TestRestartWorkerExcludesInfra:

    def test_restart_worker_excludes_infra(self, tmp_path):
        """R(정상): restart_worker("all") → infra tier 항목의 _kill_pid_file 호출되지 않음"""
        from app.modules.system.config import MANAGED_PROJECTS
        fake = copy.deepcopy(MANAGED_PROJECTS)
        fake["monitor-page"]["path"] = str(tmp_path)
        pid_dir = tmp_path / ".pids"
        pid_dir.mkdir()

        # worker tier PID 파일 생성 (통합 워커)
        (pid_dir / "unified_worker_admin.pid").write_text(str(os.getpid()))

        with patch("app.modules.system.services.system_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            killed_labels = []
            original_kill = svc._kill_pid_file

            async def tracking_kill(pid_file, label):
                killed_labels.append(label)
                return False, f"mock: {label}"

            svc._kill_pid_file = tracking_kill
            asyncio.get_event_loop().run_until_complete(svc.restart_worker("all"))

        # infra tier 항목이 kill 대상에 포함되지 않아야 함
        infra_items = [
            item for item in fake["monitor-page"]["workers"]["items"]
            if item.get("tier") == "infra"
        ]
        infra_labels = [item["label"] for item in infra_items]
        for label in infra_labels:
            assert not any(label in k for k in killed_labels), \
                f"infra 항목 '{label}'이 kill 대상에 포함됨"
