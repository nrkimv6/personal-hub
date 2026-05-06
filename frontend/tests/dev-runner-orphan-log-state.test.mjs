import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const devRunnerTab = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);
const runnerInstance = readFileSync(
  new URL("../src/lib/components/dev-runner/RunnerInstanceTab.svelte", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("runner source and tab carry orphan_alive redis_missing log_file_found", () => {
  assert.match(devRunnerTab, /orphan_alive\?: boolean/);
  assert.match(devRunnerTab, /redis_missing\?: boolean/);
  assert.match(devRunnerTab, /log_file_found\?: boolean/);
  assert.match(devRunnerTab, /orphan_alive: runner\.orphan_alive/);
  assert.match(devRunnerTab, /redis_missing: runner\.redis_missing/);
  assert.match(devRunnerTab, /log_file_found: runner\.log_file_found/);
});

test("missing runner sync keeps active tab in log probe state and catches up", () => {
  assert.match(devRunnerTab, /function preserveMissingRunnerTab/);
  assert.match(devRunnerTab, /orphan_alive: tab\.orphan_alive/);
  assert.match(devRunnerTab, /redis_missing: true/);
  assert.match(devRunnerTab, /log_file_found: tab\.log_file_found/);
  assert.match(devRunnerTab, /catchUpRunnerLogRef\(tab\.id\)/);
});

test("runner instance displays orphan alive and redis missing separately", () => {
  assert.match(runnerInstance, /orphanAlive/);
  assert.match(runnerInstance, /redisMissing/);
  assert.match(runnerInstance, /orphanAlive[\s\S]{0,220}Redis 상태 소실/);
  assert.match(runnerInstance, /redisMissing[\s\S]{0,220}로그 복구/);
});

test("empty log state exposes retry or diagnostic text instead of only no logs", () => {
  assert.match(logViewer, /emptyLogMessage/);
  assert.doesNotMatch(logViewer, /lines\.length === 0\}\s*<span class="text-gray-600">로그가 없습니다<\/span>/);
});
