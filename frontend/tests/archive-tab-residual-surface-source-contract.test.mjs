/**
 * Phase T1: ArchiveTab 잔류 surface source-contract
 *
 * ArchiveTab이 candidate/execution/queue/result/retrieval surface를 import하지 않고
 * ArchiveSyncPanel, ArchiveRecordDetailPanel만 import하는지 검증한다.
 *
 * 또한 plan-archive redirect banner/placeholder 안내가 남지 않는지 확인한다.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabPath = 'src/routes/plans/ArchiveTab.svelte';
const detailPanelPath = 'src/routes/plans/archive-tab/ArchiveRecordDetailPanel.svelte';
const syncPanelPath = 'src/routes/plans/archive-tab/ArchiveSyncPanel.svelte';

const archiveTabSource = readFileSync(archiveTabPath, 'utf8');
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

test('ArchiveTab does not import ArchiveRetrievalPanel', () => {
	assert.ok(
		!archiveTabSource.includes('./archive-tab/ArchiveRetrievalPanel.svelte'),
		`${archiveTabPath}: must NOT import ArchiveRetrievalPanel`,
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

test('ArchiveTab does not import planArchiveResidualState', () => {
	assert.ok(
		!archiveTabSource.includes('./archive-tab/planArchiveResidualState.svelte'),
		`${archiveTabPath}: must NOT import planArchiveResidualState`,
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

// ── 2. redirect banner / placeholder 안내 제거 ────────────────────────────────

test('ArchiveTab does not contain /scheduler/plan-archive redirect banner', () => {
	assert.ok(
		!archiveTabSource.includes('/scheduler/plan-archive'),
		`${archiveTabPath}: must NOT contain /scheduler/plan-archive redirect banner`,
	);
});

test('ArchiveTab does not contain placeholder announcement text', () => {
	const found =
		archiveTabSource.includes('archive 파일/DB 관리') ||
		archiveTabSource.includes('이 화면은') ||
		archiveTabSource.includes('schedule 운영');
	assert.ok(
		!found,
		`${archiveTabPath}: must NOT contain placeholder announcement about moved plan-archive operations`,
	);
});

// ── 3. 잔류 컴포넌트 Svelte parse ──────────────────────────────────────────────

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

test('ArchiveRecordDetailPanel does not contain manual reanalyze affordance', () => {
	const forbidden = ['재분석', 'reanalyz', 'requestAnalysis', 'analyzeRecord'];
	const found = forbidden.filter((token) => detailPanelSource.includes(token));
	assert.deepEqual(
		found,
		[],
		`${detailPanelPath}: must NOT contain manual reanalyze affordance: ${found.join(', ')}`,
	);
});

test('ArchiveRecordDetailPanel contains relation surface affordance', () => {
	const has =
		detailPanelSource.includes('relation') ||
		detailPanelSource.includes('관계') ||
		detailPanelSource.includes('relations');
	assert.ok(has, `${detailPanelPath}: must contain relation surface`);
});

test('ArchiveRecordDetailPanel does not contain applied request badge affordance', () => {
	const forbidden = ['appliedRequestId', 'applied_request_id', 'DB 반영됨'];
	const found = forbidden.filter((token) => detailPanelSource.includes(token));
	assert.deepEqual(
		found,
		[],
		`${detailPanelPath}: must NOT contain applied request badge: ${found.join(', ')}`,
	);
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

test('ArchiveSyncPanel does not link to /scheduler/plan-archive', () => {
	assert.ok(
		!syncPanelSource.includes('/scheduler/plan-archive'),
		`${syncPanelPath}: must NOT link to /scheduler/plan-archive`,
	);
});
