import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const logViewer = readFileSync(
  new URL('../src/lib/components/dev-runner/LogViewer.svelte', import.meta.url),
  'utf8',
);

test('LogViewer has an optional outcome summary slot near the completed banner', () => {
  assert.match(logViewer, /outcomeSummary\?:/);
  assert.match(logViewer, /data-testid="dev-runner-outcome-summary"/);
  assert.match(logViewer, /\{#if exitBanner\.show\}/);
  assert.match(logViewer, /\[OUTCOME\]/);
});
