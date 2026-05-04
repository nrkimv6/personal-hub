import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
	computeDevRunnerDirty,
	computeLlmDirty,
	formatDevRunnerSummary,
	formatLlmSummary
} from '../src/lib/utils/ai-defaults-state.js';

const llmSnapshot = {
	provider: 'claude',
	model: 'claude-sonnet',
	callerDefaults: {
		crawl: { provider: 'claude', model: 'claude-sonnet' },
		repair: { provider: 'gemini', model: 'gemini-pro' }
	}
};

test('computeLlmDirty returns clean when persisted state matches the draft', () => {
	assert.deepEqual(computeLlmDirty(llmSnapshot, structuredClone(llmSnapshot)), {
		dirty: false,
		changedFields: []
	});
});

test('computeLlmDirty reports global provider and model changes separately', () => {
	assert.deepEqual(computeLlmDirty(llmSnapshot, { ...llmSnapshot, provider: 'gemini' }), {
		dirty: true,
		changedFields: ['provider']
	});
	assert.deepEqual(computeLlmDirty(llmSnapshot, { ...llmSnapshot, model: 'claude-opus' }), {
		dirty: true,
		changedFields: ['model']
	});
});

test('computeLlmDirty reports caller-specific changes', () => {
	const result = computeLlmDirty(llmSnapshot, {
		...llmSnapshot,
		callerDefaults: {
			...llmSnapshot.callerDefaults,
			repair: { provider: 'gemini', model: 'gemini-flash' }
		}
	});
	assert.equal(result.dirty, true);
	assert.deepEqual(result.changedFields, ['caller_defaults.repair.model']);
});

test('computeDevRunnerDirty reports dev-runner engine changes', () => {
	assert.deepEqual(
		computeDevRunnerDirty(
			{ defaultEngine: 'claude', defaultFixEngine: 'codex' },
			{ defaultEngine: 'gemini', defaultFixEngine: 'codex' }
		),
		{ dirty: true, changedFields: ['defaultEngine'] }
	);
});

test('LLM dirty state does not affect dev-runner dirty state', () => {
	const changedLlm = computeLlmDirty(llmSnapshot, { ...llmSnapshot, provider: 'gemini' });
	const unchangedDevRunner = computeDevRunnerDirty(
		{ defaultEngine: 'claude', defaultFixEngine: 'codex' },
		{ defaultEngine: 'claude', defaultFixEngine: 'codex' }
	);
	assert.equal(changedLlm.dirty, true);
	assert.deepEqual(unchangedDevRunner, { dirty: false, changedFields: [] });
});

test('summary formatters include placeholders for empty values', () => {
	assert.equal(formatLlmSummary({ provider: 'claude', model: '' }), 'claude / global 기본');
	assert.equal(formatDevRunnerSummary({ defaultEngine: '', defaultFixEngine: 'codex' }), '기본 엔진 없음 / codex');
});
