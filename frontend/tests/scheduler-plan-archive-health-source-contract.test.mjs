import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const schedulerSource = readFileSync('frontend/src/routes/scheduler/ScheduleListTab.svelte', 'utf8');

test('plan-records api exposes getArchiveHealth wrapper', () => {
	assert.match(apiSource, /interface PlanArchiveHealth/);
	assert.match(apiSource, /getArchiveHealth:\s*\(includeTemp = false\)/);
	assert.match(apiSource, /\/records\/archive-health\?include_temp=/);
});

test('scheduler renders plan_archive_analyze health fields', () => {
	assert.match(schedulerSource, /planRecordsApi\.getArchiveHealth/);
	assert.match(schedulerSource, /planArchiveHealth\.real_unprocessed/);
	assert.match(schedulerSource, /planArchiveHealth\.temp_pytest_unprocessed/);
	assert.match(schedulerSource, /planArchiveHealth\.pending_or_processing_requests/);
	assert.match(schedulerSource, /planArchiveHealth\.failed_requests/);
	assert.match(schedulerSource, /planArchiveHealth\.plan_archive_schedule\?\.last_success/);
});

test('scheduler keeps disabled real backlog warning condition in source', () => {
	assert.match(schedulerSource, /planArchiveHealth\.real_unprocessed > 0 && !schedule\.enabled/);
	assert.match(schedulerSource, /미처리 보류/);
	assert.match(schedulerSource, /\/plans\?tab=archive/);
});
