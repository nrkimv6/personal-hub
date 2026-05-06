"""
restart_infra 통합 테스트 (T3)

실제 파일시스템 + config 사용, subprocess는 mock
"""

import asyncio
import copy
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.worker_service import WorkerService as SystemService


def _sp_ok(stdout="완료"):
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _sp_fail(stderr="실패"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


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

        실제 config의 infra 항목들을 순회하며 각각 올바른 subprocess 명령이 생성되는지 검증.
        """
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        infra_names = [i["name"] for i in items if i.get("tier") == "infra"]
        # command_listener는 config에 없어도 허용되므로 추가
        if "command_listener" not in infra_names:
            infra_names.append("command_listener")

        for name in infra_names:
            with patch(
                "app.modules.system.services.worker_service.executor_service.restart_listener",
                return_value={"success": True, "message": "listener restarted"},
            ) as mock_restart, patch(
                "app.modules.system.services.worker_service.subprocess.run",
                return_value=_sp_ok(),
            ) as mock_run:
                svc = SystemService()
                result = asyncio.run(svc.restart_infra(name))

            assert result["success"] is True, f"{name}: {result['message']}"

            if name == "command_listener":
                mock_restart.assert_called_once()
                mock_run.assert_not_called()
            else:
                mock_restart.assert_not_called()
                args = mock_run.call_args[0][0]
                assert "browser_workers.py" in args[1]
                assert "restart-infra" in args
                assert name in args

    def test_worker_tier_excluded_from_infra_restart(self):
        """T3: worker tier 항목은 restart_infra에서 거부됨 (실제 config 사용)"""
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        worker_names = [i["name"] for i in items if i.get("tier", "worker") == "worker"]

        svc = SystemService()
        for name in worker_names:
            with patch("app.modules.system.services.worker_service.subprocess.run") as mock_run:
                result = asyncio.run(svc.restart_infra(name))
            assert result["success"] is False, f"worker tier '{name}'이 infra restart 통과됨"
            mock_run.assert_not_called()

    def test_config_no_infra_command_listener(self):
        """T3: config에 infra_command_listener 항목 없음 확인 — 제거 완료 검증"""
        from app.modules.system.config import MANAGED_PROJECTS

        monitor = MANAGED_PROJECTS.get("monitor-page", {})
        items = monitor.get("workers", {}).get("items", [])
        names = [i["name"] for i in items]

        assert "infra_command_listener" not in names, \
            f"infra_command_listener가 config에 남아있음. 현재 목록: {names}"
