import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const runStatusBar = readFileSync(
  new URL("../src/lib/components/dev-runner/RunStatusBar.svelte", import.meta.url),
  "utf8",
);
const runnerInstanceTab = readFileSync(
  new URL("../src/lib/components/dev-runner/RunnerInstanceTab.svelte", import.meta.url),
  "utf8",
);

test("dev-runner stale badges avoid invalid {@const} placement", () => {
  for (const [name, source] of [
    ["RunStatusBar.svelte", runStatusBar],
    ["RunnerInstanceTab.svelte", runnerInstanceTab],
  ]) {
    assert.doesNotMatch(
      source,
      /\{@const\s+staleLabel\s*=/,
      `${name} must not reintroduce staleLabel {@const} in element children`,
    );
  }
});

test("RunStatusBar stale badge still renders from resolveStaleLabel", () => {
  assert.match(runStatusBar, /\{#if resolveStaleLabel\(runner\)\}/);
  assert.match(runStatusBar, /\{resolveStaleLabel\(runner\)\}/);
  assert.match(
    runStatusBar,
    /hidden shrink-0 rounded bg-muted px-1\.5 py-0\.5 text-\[10px\] text-muted-foreground md:inline-flex/,
  );
});

test("RunnerInstanceTab stale badge still renders from staleBadgeLabel", () => {
  assert.match(runnerInstanceTab, /\{#if staleBadgeLabel\(\)\}/);
  assert.match(runnerInstanceTab, /\{staleBadgeLabel\(\)\}/);
  assert.match(
    runnerInstanceTab,
    /shrink-0 px-1\.5 py-0\.5 rounded text-\[10px\] bg-muted text-muted-foreground/,
  );
});
