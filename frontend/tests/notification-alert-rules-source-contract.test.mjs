import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const component = readFileSync(
  new URL('../src/lib/components/NotificationSettings.svelte', import.meta.url),
  'utf8',
);
const commonApi = readFileSync(new URL('../src/lib/api/common.ts', import.meta.url), 'utf8');
const types = readFileSync(new URL('../src/lib/types.ts', import.meta.url), 'utf8');

assert.match(commonApi, /getAlertRules:\s*\(\)[\s\S]*\/notification\/alert-rules/);
assert.match(commonApi, /updateAlertRule:\s*\([\s\S]*ruleId/);
assert.match(types, /export interface AlertRuleSettings/);
assert.match(types, /export interface AlertRuleOverrideUpdate/);

assert.match(component, /notificationApi\.getSettings\(\)/);
assert.match(component, /notificationApi\.getAlertRules\(\)/);
assert.match(component, /notificationApi\.updateSettings\(notificationSettings\)/);
assert.match(component, /notificationApi\.updateAlertRule\(rule\.rule_id,\s*payload\)/);
assert.match(component, /rule\.locked/);
assert.match(component, /disabled=\{rule\.locked \|\| rule\.stale\}/);
assert.match(component, /ALERT_RULE_STALE_WRITE/);
assert.match(component, /LOCKED_CRITICAL_RULE/);
assert.match(component, /ALERT_POLICY_REGISTRY_MISSING/);
