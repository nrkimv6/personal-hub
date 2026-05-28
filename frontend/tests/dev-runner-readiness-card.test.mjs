import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const api = readFileSync(
  new URL("../src/lib/api/dev-runner.ts", import.meta.url),
  "utf8",
);
const runControl = readFileSync(
  new URL("../src/lib/components/dev-runner/RunControl.svelte", import.meta.url),
  "utf8",
);
const actionBar = readFileSync(
  new URL("../src/lib/components/dev-runner/execute-modal/ActionBar.svelte", import.meta.url),
  "utf8",
);
const readinessCard = readFileSync(
  new URL("../src/lib/components/dev-runner/execute-modal/ReadinessCard.svelte", import.meta.url),
  "utf8",
);

test("dev-runner API exposes a readonly readiness endpoint contract", () => {
  assert.match(api, /export interface DevRunnerReadinessResponse/);
  assert.match(api, /can_start: boolean/);
  assert.match(api, /readiness: \(\) => devRunnerRequest<DevRunnerReadinessResponse>\('\/readiness'\)/);
});

test("RunControl loads readiness and passes it to the footer gate", () => {
  assert.match(runControl, /devRunnerRunnerApi\.readiness\(\)/);
  assert.match(runControl, /<ReadinessCard/);
  assert.match(runControl, /readiness=\{readiness\}/);
});

test("ActionBar disables start when readiness has blockers", () => {
  assert.match(actionBar, /readiness\?\.can_start === false/);
  assert.match(actionBar, /Readiness 차단 항목/);
});

test("ReadinessCard renders blocker, warning, and ok states", () => {
  assert.match(readinessCard, /차단/);
  assert.match(readinessCard, /주의/);
  assert.match(readinessCard, /시작 가능/);
});
