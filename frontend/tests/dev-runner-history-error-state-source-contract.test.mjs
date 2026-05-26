import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const runHistoryPanel = read('../src/lib/components/dev-runner/RunHistoryPanel.svelte');
const unifiedLogsView = read('../src/lib/components/dev-runner/UnifiedLogsView.svelte');

test('run history panel separates history endpoint failure from empty history', () => {
	assert.match(runHistoryPanel, /historyEndpointErrorMessage/);
	assert.match(runHistoryPanel, /devRunnerLogApi\.history\(limit, offset, false\)/);
	assert.match(runHistoryPanel, /실행 이력 API 요청 실패/);
	assert.ok(runHistoryPanel.indexOf('{#if loading}') < runHistoryPanel.indexOf('{:else if error}'));
	assert.ok(runHistoryPanel.indexOf('{:else if error}') < runHistoryPanel.indexOf('실행 이력 없음'));
});

test('unified logs view separates history endpoint failure from no-run state', () => {
	assert.match(unifiedLogsView, /historyEndpointErrorMessage/);
	assert.match(unifiedLogsView, /devRunnerLogApi\.history\(10, 0, false\)/);
	assert.match(unifiedLogsView, /통합 실행 로그 API 요청 실패/);
	assert.ok(unifiedLogsView.indexOf('{#if loading}') < unifiedLogsView.indexOf('{:else if error}'));
	assert.ok(unifiedLogsView.indexOf('{:else if error}') < unifiedLogsView.indexOf('실행 이력이 없습니다'));
});
