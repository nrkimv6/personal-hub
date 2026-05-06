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

export function loadSavedTargets(): SelectedTarget[] {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];
		return JSON.parse(raw) as SelectedTarget[];
	} catch {
		return [];
	}
}

export function saveTargets(targets: SelectedTarget[]): void {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(targets));
	} catch {
		// ignore storage errors
	}
}

export function candidateActionLabel(state: string): string {
	switch (state) {
		case 'file_only': return '미리보기 후 큐잉';
		case 'matched': return '분석 큐';
		case 'db_only': return '분석 큐';
		default: return '분석 큐';
	}
}
