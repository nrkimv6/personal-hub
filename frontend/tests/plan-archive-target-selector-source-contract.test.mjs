import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const selectorSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveTargetSelector.svelte',
	'utf8'
);
const operationsStateSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/planArchiveOperationsState.ts',
	'utf8'
);
const pageSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/+page.svelte',
	'utf8'
);
const candidateTableSource = readFileSync(
	'frontend/src/routes/scheduler/plan-archive/PlanArchiveCandidateTable.svelte',
	'utf8'
);

test('PlanArchiveTargetSelector exposes provider group select and clear helpers', () => {
	assert.match(selectorSource, /function isGroupFullySelected\(provider: string\)/);
	assert.match(selectorSource, /function selectGroup\(provider: string\)/);
	assert.match(selectorSource, /function clearGroup\(provider: string\)/);
	assert.match(selectorSource, /targetSelectionKey\(t\)/);
	assert.match(selectorSource, /selectedByKey\.get\(targetSelectionKey\(t\)\) \?\? t/);
	assert.match(selectorSource, /\$\{k\} target 모두 선택/);
	assert.match(selectorSource, /\$\{k\} target 모두 해제/);
});

test('PlanArchiveTargetSelector wires popup id through aria-controls', () => {
	assert.match(selectorSource, /const POPUP_ID = 'plan-archive-target-selector-popup'/);
	assert.match(selectorSource, /aria-controls=\{POPUP_ID\}/);
	assert.match(selectorSource, /id=\{POPUP_ID\}/);
});

test('PlanArchiveTargetSelector chips use a separate remove button affordance', () => {
	assert.match(selectorSource, /aria-label="target 제거: \{targetLabel\(t\)\}"/);
	assert.match(selectorSource, /onclick=\{\(\) => removeTarget\(t\)\}/);
	assert.match(selectorSource, /flex-shrink-0/);
});

test('Plan Archive selected target payload field names stay stable', () => {
	for (const field of ['provider', 'model', 'profile_key', 'engine', 'profile_name']) {
		assert.match(operationsStateSource, new RegExp(`${field}\\??:`));
	}
	assert.match(operationsStateSource, /dedupe_key/);
	assert.match(pageSource, /selected_targets: selectedTargets/);
	assert.match(candidateTableSource, /selected_targets: selectedTargets/);
});

test('Plan Archive selector keeps cc-codex blocked from selectable targets', () => {
	assert.match(operationsStateSource, /PLAN_ARCHIVE_BLOCKED_PROVIDERS = new Set\(\['cc-codex'\]\)/);
	assert.match(selectorSource, /PLAN_ARCHIVE_BLOCKED_PROVIDERS\.has\(p\.key\)/);
});
