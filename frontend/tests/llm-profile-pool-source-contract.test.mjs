import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync(new URL('../src/lib/api/system.ts', import.meta.url), 'utf8');
const aiProfilesSource = readFileSync(new URL('../src/lib/components/system/AiProfilesSettings.svelte', import.meta.url), 'utf8');

test('profile API exposes pool metadata and status client', () => {
  assert.match(apiSource, /enabled\?: boolean/);
  assert.match(apiSource, /priority\?: number/);
  assert.match(apiSource, /last_quota_pause_until\?: string \| null/);
  assert.match(apiSource, /LLMProfileStatusItem/);
  assert.match(apiSource, /getProfileStatus:\s*\(\)\s*=>\s*request<LLMProfileStatusItem\[\]>\('\/llm\/profiles\/status'\)/);
});

test('AI profile settings exposes pool controls', () => {
  assert.match(aiProfilesSource, /getProfileStatus/);
  assert.match(aiProfilesSource, /bind:checked=\{drafts\[p\.idx\]\.enabled\}/);
  assert.match(aiProfilesSource, /bind:value=\{drafts\[p\.idx\]\.priority\}/);
  assert.match(aiProfilesSource, /pauseProfile/);
  assert.match(aiProfilesSource, /resumeProfile/);
});
