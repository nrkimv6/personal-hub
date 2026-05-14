"""LLMService Facade 회귀 TC (Task 28)."""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.services.llm_service import LLMService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def facade(db):
    return LLMService(db)


class TestFacadeEnqueue:
    def test_facade_enqueue_R_roundtrip(self, db, facade):
        """R: LLMService(db).enqueue(...) → DB 저장 확인."""
        with patch.object(facade._config_svc, "resolve_provider_model", return_value=("claude", "m1")):
            req = facade.enqueue("instagram", "post_1", "test prompt", requested_by="test")

        assert req.id is not None
        assert req.status == "pending"
        assert req.caller_type == "instagram"

    def test_facade_enqueue_B_dedup(self, db, facade):
        """B: 동일 caller 중복 enqueue → 같은 요청 반환."""
        with patch.object(facade._config_svc, "resolve_provider_model", return_value=("claude", "m1")):
            r1 = facade.enqueue("ct", "ci", "prompt1")
            r2 = facade.enqueue("ct", "ci", "prompt2")
        assert r1.id == r2.id


class TestFacadeExecuteLlm:
    def test_facade_execute_llm_R_dispatches(self, db, facade):
        """R: execute_llm → ExecutionDispatcher.dispatch 위임."""
        with patch("app.modules.claude_worker.services.executors.ExecutionDispatcher.dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"success": True, "result": "ok"}
            result = facade.execute_llm("test prompt", provider="claude", model="m")

        mock_dispatch.assert_called_once_with(
            "claude", "test prompt",
            model="m", timeout=120, parse_json=True,
            enable_tools=False, cli_options=None, profile=None,
        )
        assert result["success"] is True

    def test_facade_execute_claude_dispatches(self, db, facade):
        """R: execute_claude → ExecutionDispatcher.dispatch("claude", ...)."""
        with patch("app.modules.claude_worker.services.executors.ExecutionDispatcher.dispatch") as mock_dispatch:
            mock_dispatch.return_value = {"success": True}
            facade.execute_claude("prompt", model="m2")

        args = mock_dispatch.call_args
        assert args[0][0] == "claude"


class TestFacadeDelegation:
    def test_facade_delegates_mark_processing(self, db, facade):
        """R: mark_processing Facade 위임 확인."""
        with patch.object(facade._queue_svc, "mark_processing") as mock_mp:
            facade.mark_processing(42)
        mock_mp.assert_called_once_with(42)

    def test_facade_delegates_get_worker_status(self, db, facade):
        """R: get_worker_status Facade 위임 확인."""
        with patch.object(facade._worker_svc, "get_worker_status", return_value=None) as mock_gw:
            result = facade.get_worker_status()
        mock_gw.assert_called_once()
        assert result is None

    def test_facade_delegates_run_cleanup(self, db, facade):
        """R: run_cleanup Facade 위임 확인."""
        with patch.object(facade._stats_svc, "run_cleanup", return_value={"stale_processing": 0, "old_history": 0}) as mock_rc:
            result = facade.run_cleanup()
        mock_rc.assert_called_once()
        assert "stale_processing" in result

    def test_facade_cleanup_old_history_R_default_false(self, db, facade):
        """R: cleanup_old_history 기본 hard_delete=False 위임."""
        with patch.object(facade._stats_svc, "cleanup_old_history", return_value=1) as mock_cleanup:
            result = facade.cleanup_old_history(days=7)

        assert result == 1
        mock_cleanup.assert_called_once_with(7, False)

    def test_facade_cleanup_old_history_B_explicit_true(self, db, facade):
        """B: cleanup_old_history hard_delete=True 명시 위임 유지."""
        with patch.object(facade._stats_svc, "cleanup_old_history", return_value=1) as mock_cleanup:
            result = facade.cleanup_old_history(days=7, hard_delete=True)

        assert result == 1
        mock_cleanup.assert_called_once_with(7, True)

    def test_facade_delegates_list_requests(self, db, facade):
        """R: list_requests Facade 위임 확인."""
        with patch.object(facade._crud_svc, "list_requests", return_value={"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0}) as mock_lr:
            result = facade.list_requests(status="pending")
        mock_lr.assert_called_once()
        assert "items" in result

    def test_facade_delegates_quota_pause(self, db, facade):
        """R: quota 메서드 Facade 위임 확인."""
        with patch.object(facade._quota_svc, "get_provider_quota_pause", return_value=None) as mock_gq:
            result = facade.get_provider_quota_pause("claude")
        mock_gq.assert_called_once_with("claude")
        assert result is None
