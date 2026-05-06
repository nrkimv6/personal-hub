import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const planList = readFileSync(
  new URL("../src/lib/components/dev-runner/PlanList.svelte", import.meta.url),
  "utf8",
);
const runnerInstance = readFileSync(
  new URL("../src/lib/components/dev-runner/RunnerInstanceTab.svelte", import.meta.url),
  "utf8",
);

test("PlanList does not render implementation branch badges in the plan row", () => {
  assert.doesNotMatch(planList, /\{#if plan\.branch\}/);
  assert.doesNotMatch(planList, /\{plan\.branch\}/);
  assert.doesNotMatch(planList, /worktree_owner\s*\?\?\s*plan\.branch/);
});

test("RunnerInstance header keeps internal identifiers out of visible badges", () => {
  const header = runnerInstance.slice(
    runnerInstance.indexOf("<!-- 헤더 바 -->"),
    runnerInstance.indexOf("{#if stopError}"),
  );
  assert.match(header, /getEngineLabel\(engine\)/);
  assert.match(header, /title=\{metaTitle\}/);
  assert.doesNotMatch(header, /\{executionCount\}번째 실행/);
  assert.doesNotMatch(header, /\{runnerId\}<\/span>/);
  assert.doesNotMatch(header, /\{branch\}<\/span>/);
  assert.doesNotMatch(header, /bg-purple-100 text-purple-700/);
});
