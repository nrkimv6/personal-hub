import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const TARGETS = [
	'../src/routes/organize/dashboard/+page.svelte',
	'../src/routes/organize/move/+page.svelte',
	'../src/routes/organize/obsidian/+page.svelte',
	'../src/routes/organize/settings/+page.svelte',
	'../src/routes/organize/rules/+page.svelte',
	'../src/routes/organize/review/+page.svelte',
	'../src/routes/organize/files/+page.svelte',
	'../src/lib/stores/quotaStore.ts',
	'../src/routes/system/SleepNowTab.svelte',
	'../src/routes/automation/SleepNowTab.svelte',
	'../src/routes/system/MemoryTab.svelte',
	'../src/lib/api/expo.ts',
	'../src/lib/components/instagram/FeedCard.svelte'
];

const RAW_API_FETCH = /\bfetch\s*\(\s*(?:`[^`]*\/api\/|'[^']*\/api\/|"[^"]*\/api\/)/;

test('targeted frontend api calls avoid raw fetch literals', () => {
	const violations = [];
	for (const target of TARGETS) {
		const source = read(target);
		if (RAW_API_FETCH.test(source)) {
			violations.push(target);
		}
	}
	assert.deepEqual(violations, []);
});

test('file classifier surfaces use shared gate aware helper', () => {
	const helper = read('../src/lib/api/file-classifier.ts');
	assert.match(helper, /fetchWithTimeout/);
	assert.match(helper, /credentials: 'include'/);

	for (const target of TARGETS.filter((path) => path.includes('/organize/'))) {
		const source = read(target);
		assert.match(source, /fileClassifierFetch/);
	}
});

test('quota store reuses llm api wrapper', () => {
	const source = read('../src/lib/stores/quotaStore.ts');
	assert.match(source, /llmApi\.getQuotaStatus\(\)/);
	assert.match(source, /llmApi\.getProfileStatus\(\)/);
	assert.doesNotMatch(source, /fetch\('\/api\/v1\/llm\//);
});
