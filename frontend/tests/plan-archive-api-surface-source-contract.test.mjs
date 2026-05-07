import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const planRecordsSource = readFileSync('frontend/src/lib/api/plan-records.ts', 'utf8');
const archiveSource = readFileSync('frontend/src/lib/api/plan-archive.ts', 'utf8');
const scheduleSource = readFileSync('frontend/src/lib/api/plan-archive-schedule.ts', 'utf8');
const requestSource = readFileSync('frontend/src/lib/api/plan-records-request.ts', 'utf8');

test('plan-records.ts remains the compatibility export shim for archive APIs', () => {
	assert.match(planRecordsSource, /export \{ archiveApi \} from '\.\/plan-archive'/);
	assert.match(planRecordsSource, /export \{ archiveScheduleApi \} from '\.\/plan-archive-schedule'/);
	assert.match(planRecordsSource, /export \{ PlanRecordsRequestError, planRecordsRequest \} from '\.\/plan-records-request'/);
	assert.match(planRecordsSource, /export type \{[\s\S]*ArchivePreviewItem[\s\S]*\} from '\.\/plan-archive'/);
	assert.match(planRecordsSource, /export type \{[\s\S]*ArchiveScheduleDashboardResponse[\s\S]*\} from '\.\/plan-archive-schedule'/);
});

test('archiveApi moved to plan-archive.ts with organization wrappers intact', () => {
	assert.match(archiveSource, /export const archiveApi/);
	assert.match(archiveSource, /preview:\s*\(\)\s*=>\s*devRunnerRequest<ArchivePreviewResult>\('\/plans\/archive\/preview'\)/);
	assert.match(archiveSource, /organize:\s*\(archive_dir\?: string\)/);
	assert.match(archiveSource, /duplicates:\s*\(similarity\?: number\)/);
});

test('archiveScheduleApi exposes schedule, candidate, and execution wrappers', () => {
	assert.match(scheduleSource, /export const archiveScheduleApi/);
	for (const method of [
		'getDashboard',
		'listLLMRequests',
		'getLLMRequestDetail',
		'listScheduleRuns',
		'listExecutionAttempts',
		'runArchiveExecutions',
		'syncArchiveExecutions',
		'pause',
		'resume',
		'queueCandidates',
		'previewCandidate'
	]) {
		assert.match(scheduleSource, new RegExp(`${method}\\b`));
	}
});

test('schedule API uses the shared PlanRecordsRequestError-compatible helper', () => {
	assert.match(requestSource, /export class PlanRecordsRequestError extends Error/);
	assert.match(requestSource, /export async function planRecordsRequest/);
	assert.match(scheduleSource, /import \{ planRecordsRequest \} from '\.\/plan-records-request'/);
	assert.doesNotMatch(scheduleSource, /class PlanRecordsRequestError extends Error/);
});

