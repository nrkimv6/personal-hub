import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

function extractBalancedBody(source, openBraceIndex, label) {
	let depth = 0;
	for (let index = openBraceIndex; index < source.length; index += 1) {
		const char = source[index];
		if (char === '{') {
			depth += 1;
		} else if (char === '}') {
			depth -= 1;
			if (depth === 0) {
				return source.slice(openBraceIndex + 1, index);
			}
		}
	}
	assert.fail(`Could not find closing brace for ${label}`);
}

function extractFunctionBody(source, functionName) {
	const marker = `function ${functionName}`;
	const functionIndex = source.indexOf(marker);
	assert.notEqual(functionIndex, -1, `Could not find function ${functionName}`);
	const openBraceIndex = source.indexOf('{', functionIndex);
	assert.notEqual(openBraceIndex, -1, `Could not find function body for ${functionName}`);
	return extractBalancedBody(source, openBraceIndex, `function ${functionName}`);
}

test('merge queue panel uses API/local stable keys instead of runner_id-only keys', () => {
	const src = read('../src/lib/components/dev-runner/MergeQueuePanel.svelte');

	assert.match(src, /queue_key\?: string;/);
	assert.match(src, /function mergeItemKey\(item: MergeItem, index: number, section: string\): string/);
	assert.doesNotMatch(src, /\{#each\s+(?:activeItems|doneItems)\s+as\s+item\s+\(item\.runner_id\)\}/);
	assert.match(src, /\{#each activeItems as item, index \(mergeItemKey\(item, index, 'active'\)\)\}/);
	assert.match(src, /\{#each doneItems as item, index \(mergeItemKey\(item, index, 'completed'\)\)\}/);
});

test('merge queue list polling stays HTTP-only and SSE only belongs to selected runner logs', () => {
	const src = read('../src/lib/components/dev-runner/MergeQueuePanel.svelte');
	const loadBody = extractFunctionBody(src, 'load');
	const selectRunnerBody = extractFunctionBody(src, 'selectRunner');

	assert.match(loadBody, /devRunnerMergeApi\.queue\(\)/);
	assert.doesNotMatch(loadBody, /connectMergeStream|EventSource/);
	assert.match(selectRunnerBody, /devRunnerLogApi\.connectMergeStream\(runnerId\)/);
});

test('merge queue TypeScript response keeps queue_key optional for backward compatibility', () => {
	const src = read('../src/lib/api/dev-runner.ts');
	const interfaceIndex = src.indexOf('export interface MergeQueueItem');
	assert.notEqual(interfaceIndex, -1, 'Missing MergeQueueItem interface');
	const body = src.slice(interfaceIndex, src.indexOf('}', interfaceIndex));

	assert.match(body, /queue_key\?: string;/);
	assert.match(body, /runner_id: string;/);
});
