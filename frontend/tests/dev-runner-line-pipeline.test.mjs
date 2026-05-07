import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const pipeline = readFileSync(
  new URL("../src/lib/dev-runner/line-pipeline.ts", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("line pipeline exports the LogViewer addLine side-effect handlers", () => {
  assert.match(pipeline, /export const staleMarkingHandler/);
  assert.match(pipeline, /export const noiseIndicatorHandler/);
  assert.match(pipeline, /export const batchTrackingHandler/);
  assert.match(pipeline, /export const separatorResetHandler/);
  assert.match(pipeline, /export const failureBannerHandler/);
  assert.match(pipeline, /export const defaultLineHandlers: LineHandler\[\] = \[/);
});

test("LogViewer addLine dispatches parsed lines through the pipeline", () => {
  assert.match(logViewer, /const parsed = parseLine\(text, isStale\)/);
  assert.match(logViewer, /const context: LinePipelineContext = \{/);
  assert.match(logViewer, /for \(const handler of defaultLineHandlers\) handler\(parsed, context\)/);
  assert.match(logViewer, /pushLine\(parsed\)/);
});
