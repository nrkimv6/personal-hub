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

test("dev-runner tab maps orphan candidates without unconditional visible/alive promotion", () => {
  assert.match(devRunnerTab, /orphanCandidateToRunner/);
  assert.match(devRunnerTab, /discoverOrphanRunners\(\)/);
  assert.match(devRunnerTab, /reattachRunner\(runnerId\)/);
  assert.match(devRunnerTab, /killOrphanRunner\(runnerId\)/);
  const mapper = devRunnerTab.slice(
    devRunnerTab.indexOf("function orphanCandidateToRunner"),
    devRunnerTab.indexOf("function isVisibleRunnerSource"),
  );
  assert.match(mapper, /const canReattach = candidate\.can_reattach && candidate\.confidence !== 'low'/);
  assert.match(mapper, /const hasLivePid = typeof candidate\.pid === 'number' && candidate\.pid_kind !== 'none'/);
  assert.match(mapper, /const orphanAlive = hasLivePid \|\| canReattach/);
  assert.match(mapper, /const visible = candidate\.visible === true/);
  assert.match(mapper, /trigger:\s*candidate\.trigger \?\? null/);
  assert.match(mapper, /\n\s*visible,\n/);
  assert.doesNotMatch(mapper, /orphan_alive:\s*true/);
  assert.doesNotMatch(mapper, /visible:\s*true/);
  assert.doesNotMatch(mapper, /trigger:\s*candidate\.trigger \?\? 'user'/);
});

test("dev-runner tab removes low-confidence stale missing tabs instead of preserving forever", () => {
  assert.match(devRunnerTab, /function shouldPreserveMissingRunnerTab/);
  assert.match(devRunnerTab, /tab\.orphan_alive \|\| tab\.can_reattach/);
  assert.match(devRunnerTab, /tab\.confidence === 'high' \|\| tab\.confidence === 'medium'/);
  assert.match(devRunnerTab, /\.filter\(\(tab\): tab is RunnerTab => tab !== null\)/);
  assert.doesNotMatch(devRunnerTab, /runner \? updateRunnerTab\(tab, runner\) : preserveMissingRunnerTab\(tab\);\s*\}\);/);
});

test("runner instance exposes reattach and force-kill actions", () => {
  assert.match(runnerInstance, /상태 소실/);
  assert.match(runnerInstance, /재연결/);
  assert.match(runnerInstance, /강제 종료/);
  assert.match(runnerInstance, /onReattach/);
  assert.match(runnerInstance, /onKillOrphan/);
});
