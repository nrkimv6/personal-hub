import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const llmTab = readFileSync(new URL('../src/routes/llm/LlmTab.svelte', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../src/lib/api/system.ts', import.meta.url), 'utf8');
const quotaStore = readFileSync(new URL('../src/lib/stores/quotaStore.ts', import.meta.url), 'utf8');

test('llm queue exposes quota/window pending badges from quota-status', () => {
  assert.match(llmTab, /getPendingPauseInfo/);
  assert.match(llmTab, /__execution_window/);
  assert.match(llmTab, /시간창 보류/);
  assert.match(llmTab, /쿼터 보류/);
});

test('llm api has execution window contract and quota reason fields', () => {
  assert.match(apiSource, /getExecutionWindows/);
  assert.match(apiSource, /updateExecutionWindows/);
  assert.match(apiSource, /reason\?: string \| null/);
});

test('quota warning includes reason when available', () => {
  assert.match(quotaStore, /const reason = entry\.reason/);
  assert.match(quotaStore, /쿼터 소진\$\{reason\}/);
});
