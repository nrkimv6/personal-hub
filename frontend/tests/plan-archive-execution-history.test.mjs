import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync(new URL('../src/lib/api/plan-records.ts', import.meta.url), 'utf8');
const scheduleApiSource = readFileSync(
	new URL('../src/lib/api/plan-archive-schedule.ts', import.meta.url),
	'utf8'
);
const combinedApiSource = `${apiSource}\n${scheduleApiSource}`;
const archiveTabSource = readFileSync(new URL('../src/routes/plans/ArchiveTab.svelte', import.meta.url), 'utf8');
const historyTabSource = readFileSync(new URL('../src/routes/plans/HistoryTab.svelte', import.meta.url), 'utf8');

test('plan records API exposes archive execution history endpoint', () => {
	assert.match(combinedApiSource, /interface PlanArchiveExecutionHistoryResponse/);
	assert.match(combinedApiSource, /getArchiveExecutionHistory/);
	assert.match(combinedApiSource, /record_id/);
	assert.match(combinedApiSource, /limit/);
	assert.match(combinedApiSource, /\/records\/archive-executions\/history/);
});

test('archive tab does not render selected record execution history', () => {
	assert.doesNotMatch(archiveTabSource, /selectedExecutionHistory/);
	assert.doesNotMatch(archiveTabSource, /loadSelectedExecutionHistory/);
	assert.doesNotMatch(archiveTabSource, /detailTab === 'history'/);
	assert.doesNotMatch(archiveTabSource, /Archive execution/);
	assert.doesNotMatch(archiveTabSource, /LLM request #/);
});

test('history tab renders compact archive execution history table', () => {
	assert.match(historyTabSource, /Archive execution history/);
	assert.match(historyTabSource, /executionHistoryRecordId/);
	assert.match(historyTabSource, /planRecordsApi\.getArchiveExecutionHistory/);
	assert.match(historyTabSource, /getAttemptProfile/);
	assert.match(historyTabSource, /getExecutionStateClass/);
});
