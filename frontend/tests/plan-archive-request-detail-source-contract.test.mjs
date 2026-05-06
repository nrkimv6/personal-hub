import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const modalSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveRequestDetailModal.svelte',
	'utf8'
);

// ─── required fields: prompt, raw_response, result, cli_options, retry_count
test('request detail modal shows prompt field', () => {
	assert.match(modalSource, /request\.prompt/);
	assert.match(modalSource, /프롬프트/);
});

test('request detail modal shows raw_response field', () => {
	assert.match(modalSource, /raw_response/);
	assert.match(modalSource, /원본 응답/);
});

test('request detail modal shows parsed result', () => {
	assert.match(modalSource, /request\.result/);
	assert.match(modalSource, /분석 결과/);
});

test('request detail modal shows cli_options', () => {
	assert.match(modalSource, /cli_options/);
});

test('request detail modal shows retry_count', () => {
	assert.match(modalSource, /retry_count/);
	assert.match(modalSource, /retry/);
});

// ─── copy affordance
test('request detail modal provides copy buttons', () => {
	assert.match(modalSource, /navigator\.clipboard/);
	assert.match(modalSource, /복사/);
});

// ─── DB 반영 badge
test('request detail modal shows DB 반영됨 badge when applied', () => {
	assert.match(modalSource, /applied_request_id/);
	assert.match(modalSource, /DB 반영됨/);
});

// ─── error and failure_category display
test('request detail modal shows error_message and failure_category', () => {
	assert.match(modalSource, /error_message/);
	assert.match(modalSource, /failure_category/);
});

// ─── result parsed as JSON for pretty-print
test('request detail modal parses result as JSON', () => {
	assert.match(modalSource, /JSON\.parse/);
	assert.match(modalSource, /JSON\.stringify/);
});

// ─── collapsible prompt and raw_response (expand contract)
test('request detail modal collapses prompt and raw_response by default', () => {
	assert.match(modalSource, /showPrompt/);
	assert.match(modalSource, /showRaw/);
});

// ─── provider/model/status meta
test('request detail modal shows status, provider, model metadata', () => {
	assert.match(modalSource, /request\.status/);
	assert.match(modalSource, /request\.provider/);
	assert.match(modalSource, /request\.model/);
});
