from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SELECTOR = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveTargetSelector.svelte"
STATE = ROOT / "frontend/src/routes/scheduler/plan-archive/planArchiveOperationsState.ts"
DETAIL = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveRequestDetailModal.svelte"
QUEUE = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveQueueTable.svelte"
HISTORY = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveHistoryTable.svelte"
CANDIDATE_TABLE = ROOT / "frontend/src/routes/scheduler/plan-archive/PlanArchiveCandidateTable.svelte"
API = ROOT / "frontend/src/lib/api/plan-records.ts"


def test_plan_archive_target_selector_uses_profile_backed_targets():
    source = SELECTOR.read_text(encoding="utf-8")

    assert "llmApi.getProviders()" in source
    assert "llmApi.listProfiles()" in source
    assert "profiles.profiles" in source
    assert "profile_name: profile.name" in source
    assert "profile_key: `${profile.engine}:${profile.name}`" in source
    assert "label: `${profile.engine}/${profile.name}/" in source
    assert "profiledEngines" not in source
    assert "전체 선택" in source
    assert "aria-expanded" in source


def test_plan_archive_selected_target_contract_includes_profile_identity():
    source = STATE.read_text(encoding="utf-8")

    assert "engine?: string | null;" in source
    assert "profile_name?: string | null;" in source
    assert "label?: string | null;" in source
    assert "function targetKey" in source
    assert "function targetSelectionKey" in source
    assert "profileless:" in source
    assert "formatRunBacklogResult" in source
    assert "formatSyncExecutionsResult" in source


def test_plan_archive_target_selector_preserves_user_selected_model_payload():
    source = SELECTOR.read_text(encoding="utf-8")

    assert "providerModels = Object.fromEntries" in source
    assert "function modelOptions(provider: ProviderInfo): string[]" in source
    assert "function changeTargetModel" in source
    assert "selectedTargets = selectedTargets.map" in source
    assert "targetSelectionKey(row) === targetSelectionKey(t)" in source
    assert "withModel(row, model)" in source
    assert "onchange?.(selectedTargets)" in source
    assert "<select" in source
    assert "value={t.model}" in source
    assert "provider.models" in source


def test_plan_archive_target_readback_helpers_do_not_trust_target_label_first():
    source = STATE.read_text(encoding="utf-8")

    assert "export interface ProviderModelProfileReadback" in source
    assert "requested_target?: ProviderModelProfileReadback | null;" in source
    assert "effective_provider_model?: ProviderModelProfileReadback | null;" in source
    assert "actual_provider_model?: ProviderModelProfileReadback | null;" in source
    assert "assigned_profile?: ProviderModelProfileReadback | null;" in source
    assert "export function requestedTargetLabel" in source
    assert "export function effectiveTargetLabel" in source
    assert "export function actualTargetLabel" in source
    assert "return t.label || t.target_label || '\u2014';" in source
    assert source.index("if (t.provider) return `${t.provider}/${model}`;") < source.index("return t.label || t.target_label || '\u2014';")


def test_plan_archive_queue_detail_history_show_requested_effective_actual_targets():
    api = API.read_text(encoding="utf-8")
    detail = DETAIL.read_text(encoding="utf-8")
    queue = QUEUE.read_text(encoding="utf-8")
    history = HISTORY.read_text(encoding="utf-8")

    assert "export interface ArchiveProviderModelProfile" in api
    assert "requested_target?: ArchiveProviderModelProfile | null;" in api
    assert "effective_provider_model?: ArchiveProviderModelProfile | null;" in api
    assert "actual_provider_model?: ArchiveProviderModelProfile | null;" in api
    assert "assigned_profile?: ArchiveProviderModelProfile | null;" in api
    assert "requestedTargetLabel(request)" in detail
    assert "effectiveTargetLabel(request)" in detail
    assert "actualTargetLabel(req)" in detail
    assert "target mismatch" in detail
    assert "requestedTargetLabel(r)" in queue
    assert "effectiveTargetLabel(r)" in queue
    assert "actualTargetLabel(r)" in queue
    assert "requestedTargetLabel(a)" in history
    assert "effectiveTargetLabel(a)" in history
    assert "actualTargetLabel(a)" in history
    assert "stale_skipped" in history


def test_plan_archive_candidate_table_queues_same_selected_targets_for_all_actions():
    source = CANDIDATE_TABLE.read_text(encoding="utf-8")

    assert "async function queueSelected()" in source
    assert "candidate_keys: Array.from(selectedKeys)" in source
    assert "candidate_keys: [key]" in source
    assert source.count("selected_targets: selectedTargets") == 3
    assert source.count("selectedTargets.length === 0") >= 3
