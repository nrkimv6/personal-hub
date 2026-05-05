import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const apiSource = readFileSync(new URL('../src/lib/api/system.ts', import.meta.url), 'utf8');
const apiIndexSource = readFileSync(new URL('../src/lib/api/index.ts', import.meta.url), 'utf8');
const aiProfilesSource = readFileSync(new URL('../src/lib/components/system/AiProfilesSettings.svelte', import.meta.url), 'utf8');
const quotaStoreSource = readFileSync(new URL('../src/lib/stores/quotaStore.ts', import.meta.url), 'utf8');
const llmTabSource = readFileSync(new URL('../src/routes/writing/LlmTab.svelte', import.meta.url), 'utf8');

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

test('LLM queue exposes profile capacity block reasons', () => {
  assert.match(quotaStoreSource, /export const profileQuotaStatus = writable<ProfileQuotaStatus\[\]>\(\[\]\)/);
  assert.match(quotaStoreSource, /fetchProfileQuotaStatus/);
  assert.match(quotaStoreSource, /summarizeProfileCapacity/);
  assert.match(llmTabSource, /fetchProfileQuotaStatus\(\)/);
  assert.match(llmTabSource, /\$profileQuotaStatus/);
  assert.match(quotaStoreSource, /현재 가능한 profile 없음\(quota: \$\{quota\}, window: \$\{window\}, disabled: \$\{disabled\}, processing: \$\{processing\}\)/);
});

test('schedule profile policy API client is exposed', () => {
  assert.match(apiSource, /LLMScheduleProfilePolicyItem/);
  assert.match(apiSource, /LLM_BLOCK_REASON_LABELS/);
  assert.match(apiSource, /formatLLMBlockReason/);
  assert.match(apiSource, /pending_block_reason\?: LLMBlockReason \| null/);
  assert.match(apiSource, /listScheduleProfilePolicies/);
  assert.match(apiSource, /updateScheduleProfilePolicies/);
  assert.match(apiSource, /\/llm\/schedule-profile-policies/);
  assert.match(apiIndexSource, /type LLMScheduleProfilePolicyItem/);
  assert.match(apiIndexSource, /type LLMScheduleProfilePolicyWindow/);
});

test('LLM tab exposes schedule profile policy matrix controls', () => {
  assert.match(llmTabSource, /profilePolicy/);
  assert.match(llmTabSource, /listScheduleProfilePolicies/);
  assert.match(llmTabSource, /updateScheduleProfilePolicies/);
  assert.match(llmTabSource, /Schedule x Profile 정책/);
  assert.match(llmTabSource, /schedule_policy_off/);
  assert.match(llmTabSource, /pending_block_reason/);
  assert.match(llmTabSource, /formatLLMBlockReason/);
});

test('Plan Archive handles LLM block reason vocabulary', () => {
  const archiveTabSource = readFileSync(new URL('../src/routes/plans/ArchiveTab.svelte', import.meta.url), 'utf8');
  assert.match(archiveTabSource, /formatLLMBlockReason/);
  assert.match(archiveTabSource, /pending_block_reason/);
  assert.match(apiSource, /schedule_policy_off: '스케줄\/Profile 정책 차단'/);
});

test('AI profile status const stays in a Svelte-allowed child position', () => {
  assert.match(
    aiProfilesSource,
    /\{#each profilesForEngine\(engine\) as p \(p\.idx\)\}\s*\{@const status = statusFor\(engine, p\.name\)\}/,
    'AiProfilesSettings.svelte status {@const} must be the immediate child of the {#each} block',
  );
  assert.doesNotMatch(
    aiProfilesSource,
    /<div[^>]*>\s*\{@const status = statusFor\(engine, p\.name\)\}/,
    'Svelte const tag must be immediate child of each/if/snippet, not a plain element child',
  );
});
