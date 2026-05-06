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


def test_capacity_full_profile_is_not_selected(db):
    from app.modules.claude_worker.services.profile_claim_service import ProfileClaimService
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter
    from app.modules.claude_worker.services.profile_store import save_profiles

    save_profiles(
        {
            "selected": {"claude": "full"},
            "profiles": [
                {"engine": "claude", "name": "full", "config_dir": None, "extra_env": {}, "capacity": 1, "priority": 100},
                {"engine": "claude", "name": "open", "config_dir": None, "extra_env": {}, "capacity": 1, "priority": 1},
            ],
        }
    )
    request = LLMRequest(caller_type="plan_archive_analyze", caller_id="hash", prompt="p", provider="claude")
    db.add(request)
    db.commit()
    assert ProfileClaimService(db).claim(request.id, "claude", "full", capacity=1) is not None

    decision = LLMProfileRouter(db).select_profile("claude", request=request)

    assert decision.profile is not None
    assert decision.profile.name == "open"
