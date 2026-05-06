import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const schedulerSource = readFileSync('frontend/src/routes/scheduler/ScheduleListTab.svelte', 'utf8');
const collectScheduleSource = readFileSync('frontend/src/routes/collect/schedule/+page.svelte', 'utf8');

test('plan-records api exposes getArchiveHealth wrapper', () => {
	assert.match(apiSource, /interface PlanArchiveHealth/);
	assert.match(apiSource, /getArchiveHealth:\s*\(includeTemp = false\)/);
	assert.match(apiSource, /\/records\/archive-health\?include_temp=/);
});

test('scheduler keeps plan_archive_analyze editable as an LLM target', () => {
	assert.match(
		schedulerSource,
		/const LLM_TARGET_TYPES = \[[^\]]*'plan_archive_analyze'[^\]]*\]/
	);
	assert.match(
		collectScheduleSource,
		/const LLM_TARGET_TYPES = \[[^\]]*'plan_archive_analyze'[^\]]*\]/
	);
	assert.match(schedulerSource, /LLM_TARGET_TYPES\.includes\(editSchedule\.target_type\)/);
});

test('scheduler does not render the full plan archive health row directly', () => {
	assert.match(schedulerSource, /planRecordsApi\.getArchiveHealth/);
	assert.doesNotMatch(schedulerSource, /실제 미처리/);
	assert.doesNotMatch(schedulerSource, /임시 테스트 제외/);
	assert.doesNotMatch(schedulerSource, /큐 대기\/처리중/);
	assert.doesNotMatch(schedulerSource, /마지막 성공/);
	assert.doesNotMatch(schedulerSource, /마지막 실패/);
});

test('scheduler keeps only a compact backlog alert and archive detail link', () => {
	assert.match(schedulerSource, /planArchiveHealth\.real_unprocessed > 0 && !schedule\.enabled/);
	assert.match(schedulerSource, /Plan Archive 상세/);
	assert.match(schedulerSource, /\/plans\?tab=archive/);
});
