import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.task_schedule import TaskSchedule
from app.modules.claude_worker.models.llm_request import LLMScheduleProfilePolicy


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


def _save_profiles():
    from app.modules.claude_worker.services.profile_store import save_profiles

    save_profiles(
        {
            "selected": {"claude": "work"},
            "profiles": [
                {
                    "engine": "claude",
                    "name": "work",
                    "config_dir": None,
                    "extra_env": {},
                    "enabled": True,
                    "priority": 100,
                },
                {
                    "engine": "claude",
                    "name": "personal",
                    "config_dir": None,
                    "extra_env": {},
                    "enabled": True,
                    "priority": 10,
                },
            ],
        }
    )


def _request(caller_type="plan_archive_analyze", schedule_id=None):
    from app.modules.claude_worker.models.llm_request import LLMRequest

    options = {"schedule_id": schedule_id} if schedule_id is not None else None
    return LLMRequest(
        caller_type=caller_type,
        caller_id="r1",
        prompt="p",
        provider="claude",
        cli_options=json.dumps(options) if options else None,
    )


def test_policy_missing_keeps_profile_router_decision(profile_file, db):
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter

    _save_profiles()

    decision = LLMProfileRouter(db).select_profile("claude", request=_request())

    assert decision.profile is not None
    assert decision.profile.name == "work"


def test_target_type_policy_disables_one_profile(profile_file, db):
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter

    _save_profiles()
    db.add(
        LLMScheduleProfilePolicy(
            target_type="plan_archive_analyze",
            engine="claude",
            profile_name="work",
            enabled=False,
            priority=0,
            allowed_windows="[]",
            quiet_windows="[]",
        )
    )
    db.commit()

    decision = LLMProfileRouter(db).select_profile("claude", request=_request())

    assert decision.profile is not None
    assert decision.profile.name == "personal"


def test_schedule_id_policy_overrides_target_type_policy(profile_file, db):
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter

    _save_profiles()
    schedule = TaskSchedule(
        name="plan-archive-e2e",
        target_type="plan_archive_analyze",
        schedule_type="manual",
    )
    db.add(schedule)
    db.commit()
    db.add_all(
        [
            LLMScheduleProfilePolicy(
                target_type="plan_archive_analyze",
                engine="claude",
                profile_name="work",
                enabled=False,
                priority=0,
                allowed_windows="[]",
                quiet_windows="[]",
            ),
            LLMScheduleProfilePolicy(
                schedule_id=schedule.id,
                engine="claude",
                profile_name="work",
                enabled=True,
                priority=200,
                allowed_windows="[]",
                quiet_windows="[]",
            ),
        ]
    )
    db.commit()

    decision = LLMProfileRouter(db).select_profile("claude", request=_request(schedule_id=schedule.id))

    assert decision.profile is not None
    assert decision.profile.name == "work"


def test_all_profiles_blocked_by_policy_returns_schedule_policy_off(profile_file, db):
    from app.modules.claude_worker.services.profile_router import LLMProfileRouter

    _save_profiles()
    for profile_name in ["work", "personal"]:
        db.add(
            LLMScheduleProfilePolicy(
                target_type="plan_archive_analyze",
                engine="claude",
                profile_name=profile_name,
                enabled=False,
                priority=0,
                allowed_windows="[]",
                quiet_windows="[]",
            )
        )
    db.commit()

    decision = LLMProfileRouter(db).select_profile("claude", request=_request())

    assert decision.profile is None
    assert decision.reason == "schedule_policy_off"
    assert decision.blocked_counts == {"quota": 0, "policy": 2}
