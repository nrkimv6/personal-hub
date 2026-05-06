from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SELECTOR = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveTargetSelector.svelte"
STATE = ROOT / "frontend/src/routes/scheduler/plan-archive/planArchiveOperationsState.ts"


def test_plan_archive_target_selector_uses_profile_backed_targets():
    source = SELECTOR.read_text(encoding="utf-8")

    assert "llmApi.getProviders()" in source
    assert "llmApi.listProfiles()" in source
    assert "profiles.profiles" in source
    assert "profile_name: profile.name" in source
    assert "profile_key: `${profile.engine}:${profile.name}`" in source
    assert "label: `${profile.engine}/${profile.name}/" in source


def test_plan_archive_selected_target_contract_includes_profile_identity():
    source = STATE.read_text(encoding="utf-8")

    assert "engine?: string | null;" in source
    assert "profile_name?: string | null;" in source
    assert "label?: string | null;" in source
