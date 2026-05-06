/**
 * Phase T1: ArchiveTab 잔류 surface source-contract
 *
 * ArchiveTab이 candidate/execution/queue/result modal을 import하지 않고
 * ArchiveRetrievalPanel, ArchiveSyncPanel, ArchiveRecordDetailPanel과
 * planArchiveResidualState만 import하는지 검증한다.
 *
 * 또한 redirect banner와 placeholder 안내가 존재하는지 확인한다.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabPath = 'src/routes/plans/ArchiveTab.svelte';
const retrievalPanelPath = 'src/routes/plans/archive-tab/ArchiveRetrievalPanel.svelte';
const detailPanelPath = 'src/routes/plans/archive-tab/ArchiveRecordDetailPanel.svelte';
const syncPanelPath = 'src/routes/plans/archive-tab/ArchiveSyncPanel.svelte';

const archiveTabSource = readFileSync(archiveTabPath, 'utf8');
const retrievalPanelSource = readFileSync(retrievalPanelPath, 'utf8');
const detailPanelSource = readFileSync(detailPanelPath, 'utf8');
const syncPanelSource = readFileSync(syncPanelPath, 'utf8');

let svelteCompile = null;
let svelteCompilerLoadError = null;

try {
	({ compile: svelteCompile } = await import('svelte/compiler'));
} catch (error) {
	svelteCompilerLoadError = error;
}

function formatSvelteCompileError(error) {
	const details = [
		error?.message,
		error?.code ? `code: ${error.code}` : null,
		error?.start ? `start: ${error.start.line}:${error.start.column}` : null,
		error?.frame,
	].filter(Boolean);
	return details.join('\n');
}

// ── 1. ArchiveTab import 계약 ─────────────────────────────────────────────────

test('ArchiveTab imports ArchiveRetrievalPanel', () => {
	assert.ok(
		archiveTabSource.includes('./archive-tab/ArchiveRetrievalPanel.svelte'),
		`${archiveTabPath}: must import ArchiveRetrievalPanel`,
	);
});

test('ArchiveTab imports ArchiveRecordDetailPanel', () => {
	assert.ok(
		archiveTabSource.includes('./archive-tab/ArchiveRecordDetailPanel.svelte'),
		`${archiveTabPath}: must import ArchiveRecordDetailPanel`,
	);
});

test('ArchiveTab imports ArchiveSyncPanel', () => {
	assert.ok(
		archiveTabSource.includes('./archive-tab/ArchiveSyncPanel.svelte'),
		`${archiveTabPath}: must import ArchiveSyncPanel`,
	);
});

test('ArchiveTab imports planArchiveResidualState', () => {
	assert.ok(
		archiveTabSource.includes('./archive-tab/planArchiveResidualState.svelte'),
		`${archiveTabPath}: must import planArchiveResidualState`,
	);
});

test('ArchiveTab does not import PlanArchiveRequestDetailModal', () => {
	assert.ok(
		!archiveTabSource.includes('PlanArchiveRequestDetailModal'),
		`${archiveTabPath}: must NOT import PlanArchiveRequestDetailModal (moved to scheduler page)`,
	);
});

test('ArchiveTab does not import archive candidates or execution queue components', () => {
	const forbidden = ['archive-candidates', 'archive-executions', 'archiveExecutions', 'ArchiveCandidates'];
	const found = forbidden.filter((token) => archiveTabSource.includes(token));
	assert.deepEqual(
		found,
		[],
		`${archiveTabPath}: must NOT import removed surface components: ${found.join(', ')}`,
	);
});

// ── 2. redirect banner / placeholder 안내 ──────────────────────────────────────

test('ArchiveTab contains /scheduler/plan-archive redirect banner', () => {
	assert.ok(
		archiveTabSource.includes('/scheduler/plan-archive'),
		`${archiveTabPath}: must contain reference to /scheduler/plan-archive for redirect banner`,
	);
});

test('ArchiveTab contains placeholder announcement text', () => {
	const hasPlaceholder =
		archiveTabSource.includes('archive 파일/DB 관리') ||
		archiveTabSource.includes('이 화면은') ||
		archiveTabSource.includes('schedule 운영');
	assert.ok(
		hasPlaceholder,
		`${archiveTabPath}: must contain placeholder announcement about archive management purpose`,
	);
});

// ── 3. 잔류 컴포넌트 Svelte parse ──────────────────────────────────────────────

test(
	'ArchiveRetrievalPanel Svelte markup parses cleanly',
	{
		skip: svelteCompile
			? false
			: `svelte/compiler unavailable: ${svelteCompilerLoadError?.code ?? svelteCompilerLoadError?.message ?? 'unknown'}`,
	},
	() => {
		try {
			svelteCompile(retrievalPanelSource, { filename: retrievalPanelPath, generate: false });
		} catch (error) {
			assert.fail(`${retrievalPanelPath}: must parse cleanly.\n${formatSvelteCompileError(error)}`);
		}
	},
);

test(
	'ArchiveRecordDetailPanel Svelte markup parses cleanly',
	{
		skip: svelteCompile
			? false
			: `svelte/compiler unavailable: ${svelteCompilerLoadError?.code ?? svelteCompilerLoadError?.message ?? 'unknown'}`,
	},
	() => {
		try {
			svelteCompile(detailPanelSource, { filename: detailPanelPath, generate: false });
		} catch (error) {
			assert.fail(`${detailPanelPath}: must parse cleanly.\n${formatSvelteCompileError(error)}`);
		}
	},
);

test(
	'ArchiveSyncPanel Svelte markup parses cleanly',
	{
		skip: svelteCompile
			? false
			: `svelte/compiler unavailable: ${svelteCompilerLoadError?.code ?? svelteCompilerLoadError?.message ?? 'unknown'}`,
	},
	() => {
		try {
			svelteCompile(syncPanelSource, { filename: syncPanelPath, generate: false });
		} catch (error) {
			assert.fail(`${syncPanelPath}: must parse cleanly.\n${formatSvelteCompileError(error)}`);
		}
	},
);

// ── 4. 잔류 surface affordance 존재 확인 ─────────────────────────────────────

test('ArchiveRetrievalPanel contains retrieval/search affordance', () => {
	const has =
		retrievalPanelSource.includes('검색') ||
		retrievalPanelSource.includes('retrieval') ||
		retrievalPanelSource.includes('runRetrievalSearch');
	assert.ok(has, `${retrievalPanelPath}: must contain retrieval search affordance`);
});

test('ArchiveRetrievalPanel contains metrics affordance', () => {
	const has =
		retrievalPanelSource.includes('metrics') ||
		retrievalPanelSource.includes('메트릭') ||
		retrievalPanelSource.includes('loadRetrievalMetrics');
	assert.ok(has, `${retrievalPanelPath}: must contain metrics affordance`);
});

test('ArchiveRetrievalPanel contains archive index affordance', () => {
	const has =
		retrievalPanelSource.includes('index') ||
		retrievalPanelSource.includes('인덱스') ||
		retrievalPanelSource.includes('runArchiveIndex');
	assert.ok(has, `${retrievalPanelPath}: must contain archive index affordance`);
});

test('ArchiveRecordDetailPanel contains manual reanalyze affordance', () => {
	const has =
		detailPanelSource.includes('재분석') ||
		detailPanelSource.includes('reanalyz') ||
		detailPanelSource.includes('requestAnalysis');
	assert.ok(has, `${detailPanelPath}: must contain manual reanalyze affordance`);
});

test('ArchiveRecordDetailPanel contains relation surface affordance', () => {
	const has =
		detailPanelSource.includes('relation') ||
		detailPanelSource.includes('관계') ||
		detailPanelSource.includes('relations');
	assert.ok(has, `${detailPanelPath}: must contain relation surface`);
});

test('ArchiveRecordDetailPanel contains applied request badge affordance', () => {
	const has =
		detailPanelSource.includes('appliedRequestId') ||
		detailPanelSource.includes('applied_request_id') ||
		detailPanelSource.includes('DB 반영됨');
	assert.ok(has, `${detailPanelPath}: must contain applied request badge`);
});

test('ArchiveSyncPanel contains DB 이관 affordance', () => {
	const has =
		syncPanelSource.includes('DB 이관') ||
		syncPanelSource.includes('import') ||
		syncPanelSource.includes('onImport');
	assert.ok(has, `${syncPanelPath}: must contain DB 이관 affordance`);
});

test('ArchiveSyncPanel contains 파일/DB 동기화 affordance', () => {
	const has =
		syncPanelSource.includes('동기화') ||
		syncPanelSource.includes('sync') ||
		syncPanelSource.includes('onSync');
	assert.ok(has, `${syncPanelPath}: must contain 파일/DB 동기화 affordance`);
});

test('ArchiveSyncPanel links to /scheduler/plan-archive for execution history', () => {
	assert.ok(
		syncPanelSource.includes('/scheduler/plan-archive'),
		`${syncPanelPath}: must link to /scheduler/plan-archive for LLM queue execution history`,
	);
});
