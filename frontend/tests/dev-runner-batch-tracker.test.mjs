import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/dev-runner/batch-tracker.svelte.ts", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("BatchTracker owns PLAN_LIST, PLAN_START, PLAN_DONE, and reset behavior", () => {
  assert.match(source, /export class BatchTracker/);
  assert.match(source, /plans = \$state<BatchPlanItem\[\]>\(\[\]\)/);
  assert.match(source, /doneCount = \$derived/);
  assert.match(source, /line\.message\.match\(\^?\/\^PLAN_LIST\\s\+\(\.\+\)\$\/?/);
  assert.match(source, /line\.message\.match\(\^?\/\^PLAN_START\\s\+\(\.\+\)\$\/?/);
  assert.match(source, /line\.message\.match\(\^?\/\^PLAN_DONE\\s\+\(\.\+\)\$\/?/);
  assert.match(source, /reset\(\): void \{\s*this\.plans = \[\]/);
});

test("LogViewer uses BatchTracker instead of mutating batchPlans inline", () => {
  assert.match(logViewer, /const batchTracker = new BatchTracker\(\)/);
  assert.match(logViewer, /let batchPlans = \$derived\(batchTracker\.plans\)/);
  assert.doesNotMatch(logViewer, /batchPlans = batchPlans\.map/);
  assert.doesNotMatch(logViewer, /batchPlans = \[\]/);
});
