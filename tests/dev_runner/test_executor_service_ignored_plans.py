"""executor_service가 ignored_plans를 Redis 명령에 포함하는지 테스트"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


def test_get_ignored_plan_paths_returns_list():
    """plan_service.get_ignored_plan_paths()가 리스트를 반환하는지 확인"""
    from app.modules.dev_runner.services.plan_service import PlanService
    svc = PlanService.__new__(PlanService)
    svc._ignored_plans = ["/path/to/plan-a.md", "/path/to/plan-b.md"]
    result = svc.get_ignored_plan_paths()
    assert result == ["/path/to/plan-a.md", "/path/to/plan-b.md"]


def test_get_ignored_plan_paths_returns_copy():
    """get_ignored_plan_paths()가 원본을 변경하지 않는지 확인"""
    from app.modules.dev_runner.services.plan_service import PlanService
    svc = PlanService.__new__(PlanService)
    svc._ignored_plans = ["/path/to/plan.md"]
    result = svc.get_ignored_plan_paths()
    result.append("/extra")
    assert svc._ignored_plans == ["/path/to/plan.md"]
