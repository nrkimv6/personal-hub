from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def profile_file(tmp_path, monkeypatch):
    path = tmp_path / "llm_profiles.json"
    monkeypatch.setattr(
        "app.modules.claude_worker.services.profile_store.LLM_PROFILES_FILE",
        path,
    )
    return path


def test_profile_store_backfills_pool_fields_and_removes_secret_env(profile_file):
    from app.modules.claude_worker.services.profile_store import save_profiles

    saved = save_profiles(
        {
            "selected": {"claude": "work"},
            "profiles": [
                {
                    "engine": "claude",
                    "name": "work",
                    "config_dir": None,
                    "extra_env": {"ANTHROPIC_API_KEY": "secret", "SAFE_FLAG": "1"},
                }
            ],
        }
    )

    profile = saved["profiles"][0]
    assert profile["enabled"] is True
    assert profile["priority"] == 0
    assert profile["last_quota_pause_until"] is None
    assert profile["extra_env"] == {"SAFE_FLAG": "1"}


def test_profile_level_quota_pause_is_independent(profile_file, db):
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.profile_store import save_profiles
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    save_profiles(
        {
            "selected": {"claude": "personal"},
            "profiles": [
                {"engine": "claude", "name": "personal", "config_dir": None, "extra_env": {}},
                {"engine": "claude", "name": "work", "config_dir": None, "extra_env": {}},
            ],
        }
    )
    service = LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)

    service.set_profile_quota_pause("claude", "personal", 60_000, "quota")

    assert service.is_paused("claude", "personal") is True
    assert service.is_paused("claude", "work") is False


def test_profile_router_skips_disabled_and_paused_profiles(profile_file, db):
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter
    from app.modules.claude_worker.services.profile_store import save_profiles
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    save_profiles(
        {
            "selected": {"claude": "disabled"},
            "profiles": [
                {
                    "engine": "claude",
                    "name": "disabled",
                    "config_dir": None,
                    "extra_env": {},
                    "enabled": False,
                    "priority": 100,
                },
                {
                    "engine": "claude",
                    "name": "paused",
                    "config_dir": None,
                    "extra_env": {},
                    "priority": 50,
                    "last_quota_pause_until": (datetime.now() + timedelta(minutes=5)).isoformat(),
                },
                {
                    "engine": "claude",
                    "name": "available",
                    "config_dir": None,
                    "extra_env": {},
                    "priority": 1,
                },
            ],
        }
    )
    quota = LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)
    assert quota.get_profile_quota_pause("claude", "paused") is not None

    decision = LLMProfileRouter(db).select_profile("claude")

    assert decision.profile is not None
    assert decision.profile.name == "available"


def test_profile_claim_is_single_flight(db):
    from app.modules.claude_worker.services.profile_claim_service import ProfileClaimService

    req = LLMRequest(caller_type="test", caller_id="claim", prompt="p", provider="claude")
    db.add(req)
    db.commit()

    service = ProfileClaimService(db)
    first = service.claim(req.id, "claude", "work")
    second = service.claim(req.id, "claude", "personal")

    assert first is not None
    assert second is None

    service.release(req.id, stop_reason="completed")
    third = service.claim(req.id, "claude", "personal")

    assert third is not None
