import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const runStatusBar = readFileSync(
  new URL("../src/lib/components/dev-runner/RunStatusBar.svelte", import.meta.url),
  "utf8",
);
const devRunnerTab = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

const runnerRows = runStatusBar.slice(
  runStatusBar.indexOf("<!-- Runner 목록 행"),
  runStatusBar.indexOf("<!-- Stop/Kill/Close 아이콘 버튼 -->"),
);

test("RunStatusBar runner rows keep branch out of visible row text", () => {
  assert.match(runnerRows, /title=\{resolveMetaTitle\(runner, index\)\}/);
  assert.match(runStatusBar, /runner\.branch \? `branch: \$\{runner\.branch\}` : null/);
  assert.doesNotMatch(runnerRows, /\{#if runner\.branch\}/);
  assert.doesNotMatch(runnerRows, />\s*\{runner\.branch\}\s*<\/span>/);
});

test("RunStatusBar runner rows use plan basenames with Runner N only as fallback", () => {
  assert.match(runStatusBar, /function resolveFullLabel\(runner: RunnerTab\): string/);
  assert.match(runStatusBar, /function resolveRunnerLabel\(runner: RunnerTab, index: number\): string/);
  assert.match(runStatusBar, /return `Runner \$\{index \+ 1\}`/);
  assert.match(runnerRows, /\{resolveRunnerLabel\(runner, index\)\}/);
  assert.doesNotMatch(runStatusBar, /function resolveVisibleLabel\(index: number\): string/);
  assert.doesNotMatch(runnerRows, /runner\.plan_file\.split\(/);
});

test("RunStatusBar preserves hidden diagnostics through tooltip and selected Run meta", () => {
  assert.match(runStatusBar, /`runner: \$\{runner\.id\}`/);
  assert.match(runStatusBar, /`index: Runner \$\{index \+ 1\}`/);
  assert.match(runStatusBar, /runner\.plan_file \? `file: \$\{runner\.plan_file\}` : null/);
  assert.match(runStatusBar, /runner\.engine \? `engine: \$\{runner\.engine\}` : null/);
  assert.match(runStatusBar, /runner\.branch \? `branch: \$\{runner\.branch\}` : null/);
  assert.match(devRunnerTab, /branch=\{tab\.branch\}/);
  assert.match(logViewer, /Run meta/);
  assert.match(logViewer, /\{ label: 'Branch', value: branch \}/);
  assert.match(logViewer, /\[Branch\]/);
});
