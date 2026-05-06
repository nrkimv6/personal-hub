import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabSource = readFileSync('frontend/src/routes/plans/ArchiveTab.svelte', 'utf8');

// 이식 대상 섹션 — 전용 페이지로 이동 예정
test('ArchiveTab contains Plan Archive LLM health section (to-migrate)', () => {
	assert.match(archiveTabSource, /Plan Archive LLM health/);
	assert.match(archiveTabSource, /archiveHealth/);
});

test('ArchiveTab contains Archive execution control section (to-migrate)', () => {
	assert.match(archiveTabSource, /Archive execution control/);
	assert.match(archiveTabSource, /runArchiveExecutions|syncArchiveExecutions/);
});

test('ArchiveTab contains Plan Archive LLM 요청 section (to-migrate)', () => {
	assert.match(archiveTabSource, /Plan Archive LLM 요청/);
	assert.match(archiveTabSource, /archiveRequests|archiveQueue/);
});

test('ArchiveTab contains Archive 후보 section (to-migrate)', () => {
	assert.match(archiveTabSource, /Archive 후보/);
	assert.match(archiveTabSource, /candidateSummary/);
});

test('ArchiveTab contains LLM request result modal (to-migrate to detail modal)', () => {
	assert.match(archiveTabSource, /LLM 요청.*#\{selectedRequest\.id\}|selectedRequest/s);
	assert.match(archiveTabSource, /requestDetailRecord|requestDetailLoading/);
});

// 유지 대상 섹션 — ArchiveTab에 잔류
test('ArchiveTab contains Plan Archive retrieval section (retained)', () => {
	assert.match(archiveTabSource, /Plan Archive retrieval/);
	assert.match(archiveTabSource, /runRetrievalSearch|retrievalQ/);
});
