import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiSource = readFileSync(
  new URL("../src/lib/api/dev-runner.ts", import.meta.url),
  "utf8",
);

const planListTabSource = readFileSync(
  new URL("../src/routes/plans/PlanListTab.svelte", import.meta.url),
  "utf8",
);

test("dev runner plan API exposes storage root status contract", () => {
  assert.match(apiSource, /export interface PlanStorageRootStatusResponse/);
  assert.match(apiSource, /export interface PlanStorageRootStatusItem/);
  assert.match(apiSource, /representative_changes: PlanStorageRootChangeItem\[\]/);
  assert.match(apiSource, /storageRootsStatus: \(\) =>\s*devRunnerRequest<PlanStorageRootStatusResponse>\('\/plans\/storage-roots\/status'\)/);
});

test("Plans tab renders compact root status panel with refresh and details", () => {
  assert.match(planListTabSource, /let storageRootStatus: PlanStorageRootStatusResponse \| null = null/);
  assert.match(planListTabSource, /async function loadStorageRootStatus\(\)/);
  assert.match(planListTabSource, /Plan storage roots/);
  assert.match(planListTabSource, /dirty \{root\.dirty_count\}/);
  assert.match(planListTabSource, /\+\{root\.ahead\} -\{root\.behind\}/);
  assert.match(planListTabSource, /representative_changes/);
  assert.match(planListTabSource, /onclick=\{loadStorageRootStatus\}/);
});
