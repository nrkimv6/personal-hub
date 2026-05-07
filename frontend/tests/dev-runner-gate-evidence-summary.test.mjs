import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const apiSource = readFileSync('src/lib/api/dev-runner.ts', 'utf8');
const tabSource = readFileSync('src/routes/automation/DevRunnerTab.svelte', 'utf8');
const runnerSource = readFileSync('src/lib/components/dev-runner/RunnerInstanceTab.svelte', 'utf8');

test('dev-runner API types expose gate_evidence_summary', () => {
	assert.match(apiSource, /gate_evidence_summary\?: Record<string, unknown> \| null;/);
});

test('DevRunnerTab maps gate_evidence_summary into runner tabs', () => {
	assert.match(tabSource, /gate_evidence_summary\?: Record<string, unknown> \| null;/);
	assert.match(tabSource, /gate_evidence_summary: runner\.gate_evidence_summary \?\? null/);
	assert.match(tabSource, /gateEvidenceSummary=\{tab\.gate_evidence_summary\}/);
});

test('RunnerInstanceTab renders gate evidence reason as compact evidence badge', () => {
	assert.match(runnerSource, /function gateEvidenceLabel\(\): string \| null/);
	assert.match(runnerSource, /gateEvidenceSummary\.reason/);
	assert.match(runnerSource, /gateEvidenceTitle\(\)/);
});
