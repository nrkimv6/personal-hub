import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const archiveTabSource = readFileSync('frontend/src/routes/plans/ArchiveTab.svelte', 'utf8');
const historyTabSource = readFileSync('frontend/src/routes/plans/HistoryTab.svelte', 'utf8');

test('plan records API exposes archive execution history endpoint', () => {
	assert.match(apiSource, /interface PlanArchiveExecutionHistoryResponse/);
	assert.match(apiSource, /getArchiveExecutionHistory/);
	assert.match(apiSource, /record_id/);
	assert.match(apiSource, /limit/);
	assert.match(apiSource, /\/records\/archive-executions\/history/);
});

test('archive detail panel renders selected record execution history', () => {
	assert.match(archiveTabSource, /selectedExecutionHistory/);
	assert.match(archiveTabSource, /loadSelectedExecutionHistory/);
	assert.match(archiveTabSource, /detailTab === 'history'/);
	assert.match(archiveTabSource, /Archive execution/);
	assert.match(archiveTabSource, /LLM request #/);
});

test('history tab renders compact archive execution history table', () => {
	assert.match(historyTabSource, /Archive execution history/);
	assert.match(historyTabSource, /executionHistoryRecordId/);
	assert.match(historyTabSource, /planRecordsApi\.getArchiveExecutionHistory/);
	assert.match(historyTabSource, /getAttemptProfile/);
	assert.match(historyTabSource, /getExecutionStateClass/);
});
