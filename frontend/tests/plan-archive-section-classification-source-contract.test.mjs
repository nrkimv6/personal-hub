import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabSource = readFileSync('frontend/src/routes/plans/ArchiveTab.svelte', 'utf8');
const schedulerSource = readFileSync('frontend/src/routes/scheduler/plan-archive/+page.svelte', 'utf8');

// 이식 완료 대상 섹션 — archive 탭에 남으면 안 됨
test('ArchiveTab does not contain Plan Archive LLM health section', () => {
	assert.doesNotMatch(archiveTabSource, /Plan Archive LLM health/);
	assert.doesNotMatch(archiveTabSource, /archiveHealth/);
});

test('ArchiveTab does not contain Archive execution control section', () => {
	assert.doesNotMatch(archiveTabSource, /Archive execution control/);
	assert.doesNotMatch(archiveTabSource, /runArchiveExecutions|syncArchiveExecutions/);
});

test('ArchiveTab does not contain Plan Archive LLM request section', () => {
	assert.doesNotMatch(archiveTabSource, /Plan Archive LLM 요청/);
	assert.doesNotMatch(archiveTabSource, /archiveRequests|archiveQueue/);
});

test('ArchiveTab does not contain Archive candidate section', () => {
	assert.doesNotMatch(archiveTabSource, /Archive 후보/);
	assert.doesNotMatch(archiveTabSource, /candidateSummary/);
});

test('ArchiveTab does not contain LLM request result modal', () => {
	assert.doesNotMatch(archiveTabSource, /LLM 요청.*#\{selectedRequest\.id\}|selectedRequest/s);
	assert.doesNotMatch(archiveTabSource, /requestDetailRecord|requestDetailLoading/);
});

// 유지 대상 섹션 — ArchiveTab에 잔류
test('ArchiveTab contains Plan Archive retrieval section (retained)', () => {
	assert.match(archiveTabSource, /ArchiveRetrievalPanel/);
	assert.match(archiveTabSource, /planArchiveResidualState/);
});

test('scheduler plan archive page owns operational sections', () => {
	assert.match(schedulerSource, /PlanArchiveCandidateTable/);
	assert.match(schedulerSource, /PlanArchiveQueueTable/);
	assert.match(schedulerSource, /PlanArchiveHistoryTable/);
	assert.match(schedulerSource, /runArchiveExecutions|syncArchiveExecutions/);
});
