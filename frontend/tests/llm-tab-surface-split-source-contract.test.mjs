import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const llmDir = 'src/routes/llm';
const llmTabPath = `${llmDir}/LlmTab.svelte`;
const componentsDir = `${llmDir}/components`;
const helperPath = `${llmDir}/helpers.ts`;

const llmTabSource = readFileSync(llmTabPath, 'utf8');
const helperSource = readFileSync(helperPath, 'utf8');
const componentFiles = readdirSync(componentsDir)
	.filter((file) => file.endsWith('.svelte'))
	.map((file) => join(componentsDir, file).replaceAll('\\', '/'));

test('LlmTab orchestrates extracted llm panels', () => {
	for (const componentName of [
		'LlmOverviewPanel',
		'LlmRequestsPanel',
		'LlmRequestDetailModal',
		'LlmCreateRequestPanel',
		'LlmPolicyPanel',
	]) {
		assert.ok(
			llmTabSource.includes(componentName),
			`${llmTabPath}: must render ${componentName}`,
		);
	}
});

test('LlmTab keeps secondary TabNav contract', () => {
	assert.ok(llmTabSource.includes('<TabNav'), `${llmTabPath}: must render TabNav`);
	assert.ok(
		llmTabSource.includes('variant="secondary"'),
		`${llmTabPath}: TabNav must keep variant="secondary"`,
	);
	assert.ok(
		llmTabSource.includes('level="secondary"'),
		`${llmTabPath}: TabNav must keep level="secondary"`,
	);
});

test('LlmTab does not keep tab surface markup inline', () => {
	const forbidden = ['<table', '요청 상세 #', '수동 LLM 요청 생성', 'Schedule x Profile 정책'];
	const found = forbidden.filter((token) => llmTabSource.includes(token));
	assert.deepEqual(
		found,
		[],
		`${llmTabPath}: moved surface markup must stay in panel components: ${found.join(', ')}`,
	);
});

test('llm route sources do not add page-level title or nav surfaces', () => {
	const files = [llmTabPath, ...componentFiles];
	const failures = [];
	for (const file of files) {
		const source = readFileSync(file, 'utf8');
		for (const token of ['<h1', '<nav', 'subtitle=']) {
			if (source.includes(token)) failures.push(`${file}: ${token}`);
		}
	}
	assert.deepEqual(failures, [], `Forbidden route-owned title/nav surface found:\n${failures.join('\n')}`);
});

test('llm helpers stay pure and component-free', () => {
	const forbidden = ['$state', '$effect', '<script', 'window.', 'document.'];
	const found = forbidden.filter((token) => helperSource.includes(token));
	assert.deepEqual(found, [], `${helperPath}: helpers must remain pure: ${found.join(', ')}`);
});
