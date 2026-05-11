import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiSource = readFileSync(
  new URL("../src/lib/api/dev-runner.ts", import.meta.url),
  "utf8",
);
const devRunnerTab = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);
const runnerInstance = readFileSync(
  new URL("../src/lib/components/dev-runner/RunnerInstanceTab.svelte", import.meta.url),
  "utf8",
);

test("dev-runner API exports orphan discovery reattach and kill functions", () => {
  assert.match(apiSource, /discoverOrphanRunners/);
  assert.match(apiSource, /reattachRunner/);
  assert.match(apiSource, /killOrphanRunner/);
  assert.match(apiSource, /\/runners\/orphans/);
  assert.match(apiSource, /\/runners\/\$\{runnerId\}\/reattach/);
  assert.match(apiSource, /\/runners\/\$\{runnerId\}\/orphans\/kill/);
});

test("dev-runner tab maps orphan candidates into visible runner tabs", () => {
  assert.match(devRunnerTab, /orphanCandidateToRunner/);
  assert.match(devRunnerTab, /discoverOrphanRunners\(\)/);
  assert.match(devRunnerTab, /reattachRunner\(runnerId\)/);
  assert.match(devRunnerTab, /killOrphanRunner\(runnerId\)/);
});

test("runner instance exposes reattach and force-kill actions", () => {
  assert.match(runnerInstance, /상태 소실/);
  assert.match(runnerInstance, /재연결/);
  assert.match(runnerInstance, /강제 종료/);
  assert.match(runnerInstance, /onReattach/);
  assert.match(runnerInstance, /onKillOrphan/);
});
