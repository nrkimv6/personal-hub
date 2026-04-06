"""
restart_infra 통합 테스트 (T3)

실제 파일시스템 사용, Redis는 mock
"""

import asyncio
import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.worker_service import WorkerService as SystemService


class TestRestartInfraIntegration:

    def test_infra_restart_uses_real_config_items(self):
        """T3: config의 실제 infra items 목록을 사용해 restart_infra가 정상 동작 확인

        실제 MANAGED_PROJECTS config를 그대로 사용하여
        config 구조 변경 시 테스트가 실패하도록 보장.
        """
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        infra_items = [i for i in items if i.get("tier") == "infra"]

        # infra tier 항목이 1개 이상 존재해야 함
        assert len(infra_items) >= 1, "config에 infra tier 항목이 없음"

        # 각 infra 항목에 필수 필드 존재 확인
        for item in infra_items:
            assert "name" in item
            assert "label" in item
            assert "tier" in item
            assert item["tier"] == "infra"

    def test_infra_restart_command_listener_sends_correct_action(self):
        """T3: command_listener는 restart-listener 액션, 나머지는 restart-infra + target

        실제 config의 infra 항목들을 순회하며 각각 올바른 Redis 명령이 생성되는지 검증.
        """
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        infra_names = [i["name"] for i in items if i.get("tier") == "infra"]

        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock()
        redis_mock.brpop = AsyncMock(return_value=(
            "infra:command_results",
            json.dumps({"success": True, "message": "완료"})
        ))

        for name in infra_names:
            redis_mock.lpush = AsyncMock()

            with patch("app.shared.redis.client.RedisClient") as mock_client:
                mock_client.get_client = AsyncMock(return_value=redis_mock)
                svc = SystemService()
                result = asyncio.run(svc.restart_infra(name))

            assert result["success"] is True, f"{name}: {result['message']}"

            call_args = redis_mock.lpush.call_args
            key = call_args[0][0]
            payload = json.loads(call_args[0][1])

            assert key == "infra:commands"
            if name == "command_listener":
                assert payload["action"] == "restart-listener"
                assert "target" not in payload
            else:
                assert payload["action"] == "restart-infra"
                assert payload["target"] == name

    def test_worker_tier_excluded_from_infra_restart(self):
        """T3: worker tier 항목은 restart_infra에서 거부됨 (실제 config 사용)"""
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        worker_names = [i["name"] for i in items if i.get("tier", "worker") == "worker"]

        svc = SystemService()
        for name in worker_names:
            result = asyncio.run(svc.restart_infra(name))
            assert result["success"] is False, f"worker tier '{name}'이 infra restart 통과됨"

    def test_get_worker_status_includes_infra_command_listener(self, tmp_path):
        """T3: config에 infra_command_listener 등록 확인 — get_worker_status에 포함됨"""
        from app.modules.system.config import MANAGED_PROJECTS

        fake = copy.deepcopy(MANAGED_PROJECTS)
        fake["monitor-page"]["path"] = str(tmp_path)
        (tmp_path / ".pids").mkdir(exist_ok=True)

        with patch("app.modules.system.services.worker_service.MANAGED_PROJECTS", fake):
            svc = SystemService()
            result = asyncio.run(svc.get_worker_status())

        names = [e["name"] for e in result if e["project"] == "monitor-page"]
        assert "infra_command_listener" in names, \
            f"infra_command_listener가 worker status에 없음. 현재 목록: {names}"

        infra_listener = next(e for e in result if e["name"] == "infra_command_listener")
        assert infra_listener["tier"] == "infra"
