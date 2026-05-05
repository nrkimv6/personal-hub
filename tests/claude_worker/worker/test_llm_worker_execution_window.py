from datetime import datetime

import pytest


class _FakeDb:
    def close(self):
        pass


class _FakeDecision:
    allowed = False
    reason = "paused_by_window"
    next_allowed_at = datetime(2026, 5, 5, 19, 0)
    timezone = "Asia/Seoul"


class _FakeWindowService:
    def decide(self):
        return _FakeDecision()


class _AllowedWindowService:
    def decide(self):
        decision = _FakeDecision()
        decision.allowed = True
        decision.next_allowed_at = None
        decision.reason = None
        return decision


class _FakeService:
    executed = False

    def __init__(self, db):
        self.db = db

    def get_provider_quota_pause(self, provider):
        return None

    def get_pending_count(self):
        return 1

    def get_blocked_pending_count(self, provider):
        return 0

    def get_next_request(self, exclude_providers=None):
        self.__class__.executed = True
        return None


@pytest.mark.asyncio
async def test_process_pending_requests_keeps_pending_when_outside_execution_window(monkeypatch):
    from app.modules.claude_worker.worker import worker as worker_mod

    states = []
    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(worker_mod, "LLMService", _FakeService)
    monkeypatch.setattr(worker_mod, "LLMExecutionWindowService", _FakeWindowService)
    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: ["claude"])

    llm_worker = worker_mod.LLMWorker()
    monkeypatch.setattr(llm_worker, "_update_worker_state", lambda state, request_id=None: states.append(state))

    await llm_worker._process_pending_requests()

    assert states == ["paused_by_window"]
    assert _FakeService.executed is False


@pytest.mark.asyncio
async def test_process_pending_requests_reports_quota_pause_without_failing_pending(monkeypatch):
    from app.modules.claude_worker.worker import worker as worker_mod

    class _QuotaPausedService(_FakeService):
        def get_provider_quota_pause(self, provider):
            return datetime(2026, 5, 5, 20, 0)

        def get_blocked_pending_count(self, provider):
            return 1

        def get_next_request(self, exclude_providers=None):
            assert exclude_providers == ["claude"]
            return None

    states = []
    monkeypatch.setattr(worker_mod, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(worker_mod, "LLMService", _QuotaPausedService)
    monkeypatch.setattr(worker_mod, "LLMExecutionWindowService", _AllowedWindowService)
    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: ["claude"])

    llm_worker = worker_mod.LLMWorker()
    monkeypatch.setattr(llm_worker, "_update_worker_state", lambda state, request_id=None: states.append(state))

    await llm_worker._process_pending_requests()

    assert states == ["paused_by_quota"]
