import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync(new URL('../src/lib/api/plan-records.ts', import.meta.url), 'utf8');
const scheduleApiSource = readFileSync(new URL('../src/lib/api/plan-archive-schedule.ts', import.meta.url), 'utf8');
const combinedPlanArchiveApiSource = `${apiSource}\n${scheduleApiSource}`;
const systemSource = readFileSync(new URL('../src/lib/api/system.ts', import.meta.url), 'utf8');
const archiveTabSource = readFileSync(new URL('../src/routes/plans/ArchiveTab.svelte', import.meta.url), 'utf8');
const schedulerSource = readFileSync(new URL('../src/routes/scheduler/plan-archive/+page.svelte', import.meta.url), 'utf8');

test('plan records API exposes archive execution control contract', () => {
	assert.match(apiSource, /archive_state\?: string \| null/);
	assert.match(apiSource, /execution_state\?: string \| null/);
	assert.match(apiSource, /latest_attempt\?: PlanArchiveExecutionAttempt \| null/);
	assert.match(apiSource, /next_available_at\?: string \| null/);
	assert.match(combinedPlanArchiveApiSource, /runArchiveExecutions/);
	assert.match(combinedPlanArchiveApiSource, /\/records\/archive-executions\/run/);
	assert.match(combinedPlanArchiveApiSource, /syncArchiveExecutions/);
	assert.match(combinedPlanArchiveApiSource, /\/records\/archive-executions\/sync/);
	assert.match(combinedPlanArchiveApiSource, /selected_profiles\?: PlanArchiveSelectedProfile\[\]/);
});

test('system API exposes schedule profile policy wrappers', () => {
	assert.match(systemSource, /listScheduleProfilePolicies/);
	assert.match(systemSource, /updateScheduleProfilePolicies/);
	assert.match(systemSource, /scheduleProfilePolicyApi/);
	assert.match(systemSource, /\/llm\/schedule-profile-policies/);
});

test('scheduler plan archive page renders profile controls and execution actions', () => {
	assert.match(schedulerSource, /selectedTargets/);
	assert.match(schedulerSource, /archiveScheduleApi\.runArchiveExecutions/);
	assert.match(schedulerSource, /archiveScheduleApi\.syncArchiveExecutions/);
	assert.match(schedulerSource, /PlanArchiveCandidateTable/);
});

test('archive tab does not render profile controls or execution state badges', () => {
	assert.doesNotMatch(archiveTabSource, /Archive execution control/);
	assert.doesNotMatch(archiveTabSource, /selectedArchiveProfileKeys/);
	assert.doesNotMatch(archiveTabSource, /llmApi\.listScheduleProfilePolicies/);
	assert.doesNotMatch(archiveTabSource, /planRecordsApi\.runArchiveExecutions/);
	assert.doesNotMatch(archiveTabSource, /planRecordsApi\.syncArchiveExecutions/);
	assert.doesNotMatch(archiveTabSource, /getExecutionStateClass\(record\.execution_state\)/);
});
