import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const apiSource = readFileSync(new URL('../src/lib/api/plan-records.ts', import.meta.url), 'utf8');
const archiveTabSource = readFileSync(new URL('../src/routes/plans/ArchiveTab.svelte', import.meta.url), 'utf8');
const planViewerSource = readFileSync(new URL('../src/routes/plans/PlanViewer.svelte', import.meta.url), 'utf8');
const historyTabSource = readFileSync(new URL('../src/routes/plans/HistoryTab.svelte', import.meta.url), 'utf8');

test('plan records API exposes relation endpoints', () => {
  assert.match(apiSource, /getRelations:\s*\(/);
  assert.match(apiSource, /\/records\/\$\{id\}\/relations/);
  assert.match(apiSource, /getRelationStatistics:\s*\(\)/);
  assert.match(apiSource, /\/statistics\/relations/);
});

test('ArchiveTab and PlanViewer render relation surfaces separately from recurrence', () => {
  assert.match(archiveTabSource, /selectedRelations/);
  assert.match(archiveTabSource, /미해결 후속/);
  assert.match(planViewerSource, /계획 관계/);
  assert.match(planViewerSource, /getRelations/);
});

test('HistoryTab shows relation statistics separately', () => {
  assert.match(historyTabSource, /Plan relation statistics/);
  assert.match(historyTabSource, /getRelationStatistics/);
});
