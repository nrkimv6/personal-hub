"""ExecutionDispatcher TC (Task 24)."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def clean_registry():
    """각 테스트마다 registry를 초기 상태로 복원."""
    from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher
    original = dict(ExecutionDispatcher._registry)
    yield
    ExecutionDispatcher._registry.clear()
    ExecutionDispatcher._registry.update(original)


def _make_mock_executor(return_value=None):
    executor = MagicMock()
    executor.execute.return_value = return_value or {"success": True, "result": "ok"}
    return executor


class TestDispatchRouting:
    def test_dispatch_R_routes_to_registered_executor(self):
        """R: 등록된 executor로 dispatch."""
        from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher
        mock_exec = _make_mock_executor({"success": True, "result": "hello"})
        ExecutionDispatcher.register("test_provider", mock_exec)

        with patch("app.modules.claude_worker.services.provider_registry.get_provider") as mock_gp:
            mock_gp.return_value = MagicMock(enabled=True, executor_key="test_provider")
            result = ExecutionDispatcher.dispatch("test_provider", "test prompt", model="m1")

        mock_exec.execute.assert_called_once_with("test prompt", model="m1")
        assert result["success"] is True

    def test_dispatch_B_empty_prompt(self):
        """B: 빈 prompt도 executor까지 전달."""
        from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher
        mock_exec = _make_mock_executor({"success": True, "result": ""})
        ExecutionDispatcher.register("emp_provider", mock_exec)

        with patch("app.modules.claude_worker.services.provider_registry.get_provider") as mock_gp:
            mock_gp.return_value = MagicMock(enabled=True, executor_key="emp_provider")
            result = ExecutionDispatcher.dispatch("emp_provider", "")

        mock_exec.execute.assert_called_once_with("",)
        assert result is not None

    def test_dispatch_E_unknown_provider_returns_error(self):
        """E: 미등록 provider → success=False."""
        from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher

        with patch("app.modules.claude_worker.services.provider_registry.get_provider") as mock_gp:
            mock_gp.return_value = None
            result = ExecutionDispatcher.dispatch("nonexistent_xyz", "prompt")

        assert result["success"] is False
        assert "error" in result

    def test_dispatch_E_disabled_provider_returns_error(self):
        """E: enabled=False provider → 차단."""
        from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher
        mock_exec = _make_mock_executor()
        ExecutionDispatcher.register("disabled_prov", mock_exec)

        with patch("app.modules.claude_worker.services.provider_registry.get_provider") as mock_gp:
            mock_gp.return_value = MagicMock(enabled=False, executor_key="disabled_prov")
            result = ExecutionDispatcher.dispatch("disabled_prov", "prompt")

        mock_exec.execute.assert_not_called()
        assert result["success"] is False

    def test_register_replaces_existing_executor(self):
        """R: 동일 key 재등록 시 후자 우선."""
        from app.modules.claude_worker.services.executors.dispatcher import ExecutionDispatcher
        exec1 = _make_mock_executor({"success": True, "result": "v1"})
        exec2 = _make_mock_executor({"success": True, "result": "v2"})

        ExecutionDispatcher.register("dup_provider", exec1)
        ExecutionDispatcher.register("dup_provider", exec2)

        with patch("app.modules.claude_worker.services.provider_registry.get_provider") as mock_gp:
            mock_gp.return_value = MagicMock(enabled=True, executor_key="dup_provider")
            result = ExecutionDispatcher.dispatch("dup_provider", "p")

        exec1.execute.assert_not_called()
        exec2.execute.assert_called_once()
        assert result["result"] == "v2"
