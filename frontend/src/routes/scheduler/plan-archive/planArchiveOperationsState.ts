/**
 * Plan Archive Operations — shared state helpers (pure, no Svelte state).
 */

export interface SelectedTarget {
	provider: string;
	model: string;
	profile_key?: string | null;
	engine?: string | null;
	profile_name?: string | null;
	label?: string | null;
	kind?: 'profile' | 'engine';
}

export interface ProviderModelProfileReadback {
	provider?: string | null;
	model?: string | null;
	profile_key?: string | null;
	engine?: string | null;
	profile_name?: string | null;
	label?: string | null;
	target_label?: string | null;
}

export interface TargetReadbackSource extends ProviderModelProfileReadback {
	requested_target?: ProviderModelProfileReadback | null;
	effective_target?: ProviderModelProfileReadback | null;
	actual_target?: ProviderModelProfileReadback | null;
	effective_provider_model?: ProviderModelProfileReadback | null;
	actual_provider_model?: ProviderModelProfileReadback | null;
	assigned_profile?: ProviderModelProfileReadback | null;
}

export interface QueueResultToast {
	queued: number;
	imported: number;
	skipped: number;
	errors: number;
	details?: Array<{ key: string; reason: string }>;
}

export function formatQueueResult(r: QueueResultToast): string {
	const parts: string[] = [];
	if (r.queued > 0) parts.push(`큐잉 ${r.queued}건`);
	if (r.imported > 0) parts.push(`임포트 ${r.imported}건`);
	if (r.skipped > 0) parts.push(`스킵 ${r.skipped}건`);
	if (r.errors > 0) parts.push(`오류 ${r.errors}건`);
	return parts.join(', ') || '처리 완료';
}

export function isBulkQueueEnabled(
	selectedTargets: SelectedTarget[],
	selectedCandidates: string[]
): boolean {
	return selectedTargets.length > 0 && selectedCandidates.length > 0;
}

export function getBulkQueueDisabledReason(
	selectedTargets: SelectedTarget[],
	selectedCandidates: string[]
): string | null {
	if (selectedTargets.length === 0) return '분석 target을 1개 이상 선택하세요';
	if (selectedCandidates.length === 0) return '분석할 후보를 1개 이상 선택하세요';
	return null;
}

const STORAGE_KEY = 'plan-archive:selected-targets';

export function targetKey(t: SelectedTarget): string {
	if (t.profile_key) return `profile:${t.profile_key}`;
	const engine = (t.engine || t.provider || '').trim();
	const profileName = (t.profile_name || '').trim();
	if (engine && profileName) return `profile:${engine}:${profileName}`;
	const provider = (t.provider || 'unknown').trim() || 'unknown';
	const model = (t.model || 'default').trim() || 'default';
	return `profileless:${provider}:${model}`;
}

export function targetSelectionKey(t: SelectedTarget): string {
	if (t.profile_key) return `profile:${t.profile_key}`;
	const engine = (t.engine || t.provider || '').trim();
	const profileName = (t.profile_name || '').trim();
	if (engine && profileName) return `profile:${engine}:${profileName}`;
	const provider = (t.provider || 'unknown').trim() || 'unknown';
	return `profileless:${provider}`;
}

export function targetLabel(t: SelectedTarget): string {
	const structured = providerModelProfileLabel(t);
	if (structured !== '—') return structured;
	if (t.label) return t.label;
	return '—';
}

export function providerModelProfileLabel(t: ProviderModelProfileReadback | null | undefined): string {
	if (!t) return '—';
	const model = (t.model || '').trim() || 'default';
	if (t.profile_name) {
		const engine = (t.engine || t.provider || '').trim();
		return `${engine}/${t.profile_name}/${model}`;
	}
	if (t.provider) return `${t.provider}/${model}`;
	return t.label || t.target_label || '—';
}

function mergeAssignedProfile(
	base: ProviderModelProfileReadback | null | undefined,
	assigned: ProviderModelProfileReadback | null | undefined
): ProviderModelProfileReadback | null {
	if (!base && !assigned) return null;
	const baseProvider = base?.provider?.trim();
	const assignedEngine = assigned?.engine?.trim();
	if (baseProvider && assignedEngine && baseProvider !== assignedEngine) {
		return base ?? null;
	}
	return {
		...(base ?? {}),
		engine: base?.engine ?? assigned?.engine ?? null,
		profile_name: base?.profile_name ?? assigned?.profile_name ?? null,
		profile_key: base?.profile_key ?? assigned?.profile_key ?? null,
	};
}

export function requestedTargetLabel(source: TargetReadbackSource): string {
	return providerModelProfileLabel(source.requested_target ?? source);
}

export function effectiveTargetLabel(source: TargetReadbackSource): string {
	return providerModelProfileLabel(
		mergeAssignedProfile(source.effective_provider_model ?? source.effective_target ?? source, source.assigned_profile)
	);
}

export function actualTargetLabel(source: TargetReadbackSource): string {
	return providerModelProfileLabel(
		mergeAssignedProfile(source.actual_provider_model ?? source.actual_target ?? source, source.assigned_profile)
	);
}

export function hasTargetMismatch(source: TargetReadbackSource): boolean {
	const requested = requestedTargetLabel(source);
	const effective = effectiveTargetLabel(source);
	const actual = actualTargetLabel(source);
	return requested !== '—' && ((effective !== '—' && requested !== effective) || (actual !== '—' && requested !== actual));
}

function normalizeTarget(raw: unknown): SelectedTarget | null {
	if (!raw || typeof raw !== 'object') return null;
	const r = raw as Record<string, unknown>;
	const provider = String(r.provider || '').trim();
	if (!provider) return null;
	const model = String(r.model || '').trim();
	const profile_key = r.profile_key === undefined ? undefined : (r.profile_key as string | null);
	const engine = r.engine === undefined ? undefined : (r.engine as string | null);
	const profile_name = r.profile_name === undefined ? undefined : (r.profile_name as string | null);
	const label = r.label === undefined ? undefined : (r.label as string | null);
	const kind = r.kind === 'profile' || r.kind === 'engine' ? (r.kind as 'profile' | 'engine') : undefined;
	return {
		provider,
		model,
		profile_key: profile_key ?? null,
		engine: engine ?? null,
		profile_name: profile_name ?? null,
		label: label ?? null,
		kind,
	};
}

export function loadSavedTargets(): SelectedTarget[] {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];
		return parsed.map(normalizeTarget).filter((t): t is SelectedTarget => Boolean(t));
	} catch {
		return [];
	}
}

export function saveTargets(targets: SelectedTarget[]): void {
	try {
		const normalized = targets.map(normalizeTarget).filter((t): t is SelectedTarget => Boolean(t));
		localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
	} catch {
		// ignore storage errors
	}
}

export interface RunBacklogToast {
	queued?: number;
	skipped?: number;
	updated?: number;
}

export function formatRunBacklogResult(r: RunBacklogToast): string {
	const parts: string[] = [];
	if ((r.queued ?? 0) > 0) parts.push(`큐잉 ${r.queued}건`);
	if ((r.updated ?? 0) > 0) parts.push(`업데이트 ${r.updated}건`);
	if ((r.skipped ?? 0) > 0) parts.push(`스킵 ${r.skipped}건`);
	return parts.join(', ') || '처리 완료';
}

export interface SyncExecutionsToast {
	updated?: number;
}

export function formatSyncExecutionsResult(r: SyncExecutionsToast): string {
	if ((r.updated ?? 0) > 0) return `동기화 ${r.updated}건`;
	return '동기화 완료';
}

export function candidateActionLabel(state: string): string {
	switch (state) {
		case 'file_only': return '미리보기 후 큐잉';
		case 'matched': return '분석 큐';
		case 'db_only': return '분석 큐';
		default: return '분석 큐';
	}
}
