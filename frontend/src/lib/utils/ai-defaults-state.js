/**
 * @typedef {{ provider?: string | null, model?: string | null }} LlmDefaultValue
 * @typedef {{ provider?: string | null, model?: string | null, callerDefaults?: Record<string, LlmDefaultValue> }} LlmSnapshot
 * @typedef {LlmSnapshot} LlmDraft
 * @typedef {{ defaultEngine?: string | null, defaultFixEngine?: string | null }} DevRunnerSnapshot
 * @typedef {DevRunnerSnapshot} DevRunnerDraft
 * @typedef {{ dirty: boolean, changedFields: string[] }} DirtyResult
 */

/**
 * @param {unknown} value
 * @returns {string}
 */
function normalizeText(value) {
	return String(value ?? '').trim();
}

/**
 * @param {LlmDefaultValue | null | undefined} value
 * @returns {{ provider: string, model: string }}
 */
function normalizeLlmValue(value) {
	return {
		provider: normalizeText(value?.provider),
		model: normalizeText(value?.model)
	};
}

/**
 * @param {LlmSnapshot | null | undefined} snapshot
 * @param {LlmDraft | null | undefined} draft
 * @returns {DirtyResult}
 */
export function computeLlmDirty(snapshot, draft) {
	const changedFields = [];
	const persisted = normalizeLlmValue(snapshot);
	const current = normalizeLlmValue(draft);

	if (persisted.provider !== current.provider) changedFields.push('provider');
	if (persisted.model !== current.model) changedFields.push('model');

	const callerDefaults = snapshot?.callerDefaults ?? {};
	const callerDrafts = draft?.callerDefaults ?? {};
	const callerTypes = new Set([...Object.keys(callerDefaults), ...Object.keys(callerDrafts)]);
	for (const callerType of [...callerTypes].sort()) {
		const persistedCaller = normalizeLlmValue(callerDefaults[callerType]);
		const currentCaller = normalizeLlmValue(callerDrafts[callerType]);
		if (persistedCaller.provider !== currentCaller.provider) {
			changedFields.push(`caller_defaults.${callerType}.provider`);
		}
		if (persistedCaller.model !== currentCaller.model) {
			changedFields.push(`caller_defaults.${callerType}.model`);
		}
	}

	return { dirty: changedFields.length > 0, changedFields };
}

/**
 * @param {DevRunnerSnapshot | null | undefined} snapshot
 * @param {DevRunnerDraft | null | undefined} draft
 * @returns {DirtyResult}
 */
export function computeDevRunnerDirty(snapshot, draft) {
	const changedFields = [];
	if (normalizeText(snapshot?.defaultEngine) !== normalizeText(draft?.defaultEngine)) {
		changedFields.push('defaultEngine');
	}
	if (normalizeText(snapshot?.defaultFixEngine) !== normalizeText(draft?.defaultFixEngine)) {
		changedFields.push('defaultFixEngine');
	}
	return { dirty: changedFields.length > 0, changedFields };
}

/**
 * @param {LlmSnapshot | null | undefined} snapshot
 * @returns {string}
 */
export function formatLlmSummary(snapshot) {
	const provider = normalizeText(snapshot?.provider) || 'global 기본';
	const model = normalizeText(snapshot?.model) || 'global 기본';
	return `${provider} / ${model}`;
}

/**
 * @param {DevRunnerSnapshot | null | undefined} snapshot
 * @returns {string}
 */
export function formatDevRunnerSummary(snapshot) {
	const defaultEngine = normalizeText(snapshot?.defaultEngine) || '기본 엔진 없음';
	const defaultFixEngine = normalizeText(snapshot?.defaultFixEngine) || '기본 수정 엔진 없음';
	return `${defaultEngine} / ${defaultFixEngine}`;
}
