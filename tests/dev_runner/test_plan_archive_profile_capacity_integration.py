from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.modules.claude_worker.services.profile_store.LLM_PROFILES_FILE",
        tmp_path / "llm_profiles.json",
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _save_profiles():
    from app.modules.claude_worker.services.profile_store import save_profiles

    save_profiles(
        {
            "selected": {"claude": "a"},
            "profiles": [
                {"engine": "claude", "name": "a", "config_dir": None, "extra_env": {}, "priority": 100, "capacity": 1},
                {"engine": "claude", "name": "b", "config_dir": None, "extra_env": {}, "priority": 1, "capacity": 1},
            ],
        }
    )


def test_profile_a_capacity_full_lets_profile_b_take_archive_job(db):
    from app.modules.claude_worker.services.profile_claim_service import ProfileClaimService
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter

    _save_profiles()
    busy = LLMRequest(caller_type="plan_archive_analyze", caller_id="busy", prompt="p", provider="claude")
    incoming = LLMRequest(caller_type="plan_archive_analyze", caller_id="incoming", prompt="p", provider="claude")
    db.add_all([busy, incoming])
    db.commit()
    assert ProfileClaimService(db).claim(busy.id, "claude", "a", capacity=1) is not None

    decision = LLMProfileRouter(db).select_profile("claude", request=incoming)

    assert decision.profile is not None
    assert decision.profile.name == "b"


def test_quota_paused_profile_exposes_next_available_at(db):
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    _save_profiles()
    quota = LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)
    paused_until = quota.set_profile_quota_pause("claude", "a", 60_000, "quota")

    decision = LLMProfileRouter(db).select_profile("claude")

    assert decision.profile is not None
    assert decision.profile.name == "b"
    assert paused_until > datetime.now() - timedelta(seconds=1)
