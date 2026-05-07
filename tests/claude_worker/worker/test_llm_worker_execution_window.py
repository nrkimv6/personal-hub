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


def test_executor_cli_options_R_strips_plan_archive_metadata_for_codex():
    from app.modules.claude_worker.worker import worker as worker_mod

    cli_options = {
        "parse_json": True,
        "cwd": "D:/work/project/tools/monitor-page",
        "sandbox": "workspace-write",
        "candidate_profiles": [{"engine": "gemini", "profile_name": "default"}],
        "plan_archive_execution_job_id": 41,
        "prompt_policy_id": "plan_archive.codex.default",
        "target_label": "gemini/default/gpt-5.5",
    }

    assert worker_mod._executor_cli_options("codex", cli_options) == {
        "parse_json": True,
        "cwd": "D:/work/project/tools/monitor-page",
        "sandbox": "workspace-write",
    }


def test_executor_cli_options_R_keeps_only_gemini_image_path():
    from app.modules.claude_worker.worker import worker as worker_mod

    cli_options = {
        "parse_json": True,
        "image_path": "D:/fixtures/sample.png",
        "candidate_profiles": [{"engine": "gemini", "profile_name": "default"}],
        "requested_target": {"provider": "gemini", "model": "gemini-3.1-pro"},
    }

    assert worker_mod._executor_cli_options("gemini", cli_options) == {
        "image_path": "D:/fixtures/sample.png",
    }


def test_profile_route_providers_R_ignores_mismatched_legacy_candidate_profiles(monkeypatch):
    from app.modules.claude_worker.worker import worker as worker_mod

    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: ["claude", "gemini"])
    cli_options = {
        "candidate_profiles": [{"engine": "gemini", "profile_name": "default"}],
        "requested_target": {"provider": "codex", "model": "gpt-5.5"},
    }

    assert worker_mod._profile_route_providers("codex", "plan_archive_analyze", cli_options) == ["codex"]


def test_profile_route_providers_R_keeps_matching_profile_target(monkeypatch):
    from app.modules.claude_worker.worker import worker as worker_mod

    monkeypatch.setattr(worker_mod.provider_registry, "get_quota_providers", lambda: ["claude", "gemini"])
    cli_options = {
        "candidate_profiles": [{"engine": "gemini", "profile_name": "default"}],
        "requested_target": {"provider": "gemini", "model": "gemini-3.1-pro"},
    }

    assert worker_mod._profile_route_providers("gemini", "plan_archive_analyze", cli_options) == ["gemini"]


def test_worker_runtime_readiness_snapshot_R_includes_session_and_binary_without_userprofile_secret(monkeypatch):
    from app.modules.claude_worker.worker import worker as worker_mod

    monkeypatch.setattr(
        "app.modules.claude_worker.services.executors.gemini_executor._resolve_gemini_binary",
        lambda env: "C:/Users/test/AppData/Roaming/npm/gemini.cmd",
    )
    snapshot = worker_mod._worker_runtime_readiness_snapshot({
        "SESSIONNAME": "Console",
        "USERNAME": "Narang",
        "USERPROFILE": "C:/Users/Narang",
        "APP_MODE": "dev",
        "PATH": "C:/one;C:/two;C:/three;C:/four;C:/five",
    })

    assert snapshot["session_name"] == "Console"
    assert snapshot["username"] == "Narang"
    assert snapshot["userprofile_present"] is True
    assert snapshot["app_mode"] == "dev"
    assert snapshot["gemini_binary"].endswith("gemini.cmd")
    assert "USERPROFILE" not in snapshot


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
