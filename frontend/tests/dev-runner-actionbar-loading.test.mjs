import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const actionBar = readFileSync(
  new URL("../src/lib/components/dev-runner/execute-modal/ActionBar.svelte", import.meta.url),
  "utf8",
);
const runControl = readFileSync(
  new URL("../src/lib/components/dev-runner/RunControl.svelte", import.meta.url),
  "utf8",
);

test("ActionBar labels depend on activeAction instead of the global loading flag", () => {
  assert.match(actionBar, /activeAction:\s*RunAction \| null/);
  assert.match(actionBar, /isActive\('start'\).*'시작 중\.\.\.'/s);
  assert.match(actionBar, /isActive\('stop'\).*'중지 중\.\.\.'/s);
  assert.match(actionBar, /isActive\('sync'\).*'동기화 중\.\.\.'/s);
  assert.doesNotMatch(actionBar, /\{actionLoading \? '초기화 중\.\.\.'/);
  assert.doesNotMatch(actionBar, /\{actionLoading \? '삭제 중\.\.\.'/);
  assert.doesNotMatch(actionBar, /\{actionLoading \? '동기화 중\.\.\.'/);
});

test("RunControl records the concrete action that is currently pending", () => {
  assert.match(runControl, /type RunAction = 'start' \| 'sync' \| 'reset' \| 'fullReset' \| 'stop' \| 'forceStop'/);
  assert.match(runControl, /let activeAction = \$state<RunAction \| null>\(null\)/);
  assert.match(runControl, /activeAction = 'start'/);
  assert.match(runControl, /activeAction = 'sync'/);
  assert.match(runControl, /activeAction = fullReset \? 'fullReset' : 'reset'/);
  assert.match(runControl, /activeAction=\{activeAction\}/);
});
