import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const systemSource = readFileSync('frontend/src/lib/api/system.ts', 'utf8');
const archiveTabSource = readFileSync('frontend/src/routes/plans/ArchiveTab.svelte', 'utf8');

test('plan records API exposes archive execution control contract', () => {
	assert.match(apiSource, /archive_state\?: string \| null/);
	assert.match(apiSource, /execution_state\?: string \| null/);
	assert.match(apiSource, /latest_attempt\?: PlanArchiveExecutionAttempt \| null/);
	assert.match(apiSource, /next_available_at\?: string \| null/);
	assert.match(apiSource, /runArchiveExecutions/);
	assert.match(apiSource, /\/records\/archive-executions\/run/);
	assert.match(apiSource, /syncArchiveExecutions/);
	assert.match(apiSource, /\/records\/archive-executions\/sync/);
	assert.match(apiSource, /selected_profiles\?: PlanArchiveSelectedProfile\[\]/);
});

test('system API exposes schedule profile policy wrappers', () => {
	assert.match(systemSource, /listScheduleProfilePolicies/);
	assert.match(systemSource, /updateScheduleProfilePolicies/);
	assert.match(systemSource, /scheduleProfilePolicyApi/);
	assert.match(systemSource, /\/llm\/schedule-profile-policies/);
});

test('archive tab renders profile controls and execution state badges', () => {
	assert.match(archiveTabSource, /Archive execution control/);
	assert.match(archiveTabSource, /selectedArchiveProfileKeys/);
	assert.match(archiveTabSource, /llmApi\.listScheduleProfilePolicies/);
	assert.match(archiveTabSource, /planRecordsApi\.runArchiveExecutions/);
	assert.match(archiveTabSource, /planRecordsApi\.syncArchiveExecutions/);
	assert.match(archiveTabSource, /getExecutionStateClass\(record\.execution_state\)/);
	assert.match(archiveTabSource, /record\.archive_state/);
});
