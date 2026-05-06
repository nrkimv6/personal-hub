import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("LogViewer exposes hidden runner metadata without adding a fake log line", () => {
  assert.match(logViewer, /runMetaExpanded/);
  assert.match(logViewer, /Run meta/);
  assert.match(logViewer, /\{ label: 'Runner', value: runnerId \}/);
  assert.match(logViewer, /\{ label: 'Branch', value: branch \}/);
  assert.match(logViewer, /\{ label: 'Execution #', value: String\(executionCount\) \}/);
  assert.match(logViewer, /\[Branch\]/);
  assert.match(logViewer, /\[Execution\]/);
  assert.doesNotMatch(logViewer, /addLine\([^)]*Run meta/s);
});

test("LogViewer hides the Live Logs label on mobile", () => {
  assert.match(logViewer, /class="hidden text-xs font-medium uppercase tracking-wider text-gray-300 sm:inline">Live Logs/);
});
