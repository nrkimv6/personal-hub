import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const pageSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/+page.svelte',
	'utf8'
);
const summaryPanelSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveSummaryPanel.svelte',
	'utf8'
);
const queueTableSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveQueueTable.svelte',
	'utf8'
);
const historyTableSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveHistoryTable.svelte',
	'utf8'
);
const candidateTableSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveCandidateTable.svelte',
	'utf8'
);
const targetSelectorSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveTargetSelector.svelte',
	'utf8'
);
const operationsStateSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/planArchiveOperationsState.ts',
	'utf8'
);
const apiSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const scheduleApiSource = readFileSync('frontend/src/lib/api/plan-archive-schedule.ts', 'utf8');
const requestApiSource = readFileSync('frontend/src/lib/api/plan-records-request.ts', 'utf8');

// ─── anti-regression: "2000건 중 8건" — list tables must NOT use dashboard summary
test('PlanArchiveQueueTable uses pagination endpoint, not dashboard summary', () => {
	assert.match(queueTableSource, /listLLMRequests/);
	assert.doesNotMatch(queueTableSource, /getDashboard/);
	assert.doesNotMatch(queueTableSource, /recent_requests/);
	assert.doesNotMatch(queueTableSource, /dashboard\.queue/);
});

test('PlanArchiveHistoryTable uses pagination endpoints, not dashboard summary', () => {
	assert.match(historyTableSource, /listScheduleRuns/);
	assert.match(historyTableSource, /listExecutionAttempts/);
	assert.doesNotMatch(historyTableSource, /getDashboard/);
	assert.doesNotMatch(historyTableSource, /recent_requests/);
});

// ─── pagination contract: all list components use createPagePagination
test('PlanArchiveQueueTable imports createPagePagination and uses pager', () => {
	assert.match(queueTableSource, /createPagePagination/);
	assert.match(queueTableSource, /pager\.page/);
	assert.doesNotMatch(queueTableSource, /let offset\s*=/);
	assert.doesNotMatch(queueTableSource, /let hasMore\s*=/);
});

test('PlanArchiveHistoryTable imports createPagePagination and uses pager', () => {
	assert.match(historyTableSource, /createPagePagination/);
	assert.match(historyTableSource, /schedulePager\.page/);
	assert.match(historyTableSource, /attemptPager\.page/);
	assert.doesNotMatch(historyTableSource, /let offset\s*=/);
	assert.doesNotMatch(historyTableSource, /let hasMore\s*=/);
});

test('PlanArchiveCandidateTable imports createPagePagination and uses pager', () => {
	assert.match(candidateTableSource, /createPagePagination/);
	assert.match(candidateTableSource, /pager\.page/);
	assert.doesNotMatch(candidateTableSource, /let offset\s*=/);
	assert.doesNotMatch(candidateTableSource, /let hasMore\s*=/);
});

// ─── history default filter is empty; queue keeps pending/processing/failed default
test('PlanArchiveHistoryTable default status filter is empty (전체 표시)', () => {
	assert.match(historyTableSource, /scheduleStatusFilter = \$state\(''\)/);
	assert.match(historyTableSource, /attemptStatusFilter = \$state\(''\)/);
});

test('PlanArchiveQueueTable default status filter includes pending/processing/failed', () => {
	assert.match(queueTableSource, /statusFilter = \$state\('pending,processing,failed'\)/);
});

// ─── codex/gpt-5.5 default target
test('PlanArchiveTargetSelector includes codex/gpt-5.5 in default targets', () => {
	assert.match(targetSelectorSource, /gpt-5\.5/);
	assert.match(targetSelectorSource, /codex/);
});

// ─── component split: candidate table uses selectedTargets prop
test('PlanArchiveCandidateTable receives selectedTargets as prop', () => {
	assert.match(candidateTableSource, /selectedTargets/);
	assert.match(candidateTableSource, /onQueueSuccess/);
});

// ─── route shell is the only polling owner
test('page.svelte owns the polling timer (POLL_NORMAL_MS / schedulePoll)', () => {
	assert.match(pageSource, /POLL_NORMAL_MS/);
	assert.match(pageSource, /schedulePoll/);
	assert.match(pageSource, /pollTimer/);
});

test('list components do not self-poll (no setTimeout/setInterval in list files)', () => {
	assert.doesNotMatch(queueTableSource, /setTimeout|setInterval/);
	assert.doesNotMatch(historyTableSource, /setTimeout|setInterval/);
	assert.doesNotMatch(candidateTableSource, /setTimeout|setInterval/);
});

// ─── polling policy: visibility hidden stops polling, backoff after 3 failures
test('page.svelte pauses polling when document is hidden', () => {
	assert.match(pageSource, /visibilityState/);
	assert.match(pageSource, /visibilitychange/);
});

test('page.svelte backs off polling after 3 consecutive failures', () => {
	assert.match(pageSource, /pollFailCount/);
	assert.match(pageSource, /POLL_BACKOFF_MS/);
	assert.match(pageSource, /pollFailCount >= 3/);
});

test('PlanArchiveSummaryPanel hides mutation buttons when schedule is null', () => {
	assert.match(summaryPanelSource, /sched === null/);
	assert.match(summaryPanelSource, /\{#if sched && enabled === true\}/);
	assert.match(summaryPanelSource, /\{:else if sched && enabled === false\}/);
});

test('page.svelte distinguishes schedule missing from admin proxy route 404', () => {
	assert.match(pageSource, /PlanRecordsRequestError/);
	assert.match(pageSource, /SCHEDULE_NOT_FOUND_DETAIL/);
	assert.match(pageSource, /admin API proxy 또는 admin route mismatch/);
	assert.match(pageSource, /Plan Archive schedule seed 또는 DB 상태/);
});

// ─── target localStorage persistence (key lives in operationsState module)
test('planArchiveOperationsState defines localStorage key plan-archive:selected-targets', () => {
	assert.match(operationsStateSource, /plan-archive:selected-targets/);
});

test('PlanArchiveTargetSelector delegates localStorage to loadSavedTargets/saveTargets', () => {
	assert.match(targetSelectorSource, /loadSavedTargets/);
	assert.match(targetSelectorSource, /saveTargets/);
});

// ─── API source-contract: all required wrappers exported
test('plan-records.ts exports archiveScheduleApi with required wrappers', () => {
	assert.match(apiSource, /export \{ archiveScheduleApi \} from '\.\/plan-archive-schedule'/);
	assert.match(scheduleApiSource, /getDashboard/);
	assert.match(scheduleApiSource, /listLLMRequests/);
	assert.match(scheduleApiSource, /getLLMRequestDetail/);
	assert.match(scheduleApiSource, /listScheduleRuns/);
	assert.match(scheduleApiSource, /listExecutionAttempts/);
	assert.match(scheduleApiSource, /pause\b/);
	assert.match(scheduleApiSource, /resume\b/);
	assert.match(scheduleApiSource, /queueCandidates/);
	assert.match(scheduleApiSource, /previewCandidate/);
	assert.match(scheduleApiSource, /archiveScheduleApi/);
	assert.match(requestApiSource, /class PlanRecordsRequestError extends Error/);
});
