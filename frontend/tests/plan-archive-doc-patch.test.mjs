import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiSource = readFileSync(new URL("../src/lib/api/plan-records.ts", import.meta.url), "utf8");
const tabSource = readFileSync(new URL("../src/routes/plans/InsightReportTab.svelte", import.meta.url), "utf8");

test("doc patch API wrapper exposes preview apply and reject endpoints", () => {
	assert.match(apiSource, /PlanArchiveDocPatchProposal/);
	assert.match(apiSource, /previewDocPatch/);
	assert.match(apiSource, /applyDocPatch/);
	assert.match(apiSource, /rejectDocPatch/);
	assert.match(apiSource, /\/doc-patches\/preview/);
	assert.match(apiSource, /\/doc-patches\/\$\{id\}\/apply/);
});

test("insight tab exposes doc patch preview and confirm apply state", () => {
	assert.match(tabSource, /Doc patch proposal/);
	assert.match(tabSource, /patch proposal/);
	assert.match(tabSource, /previewDocPatch/);
	assert.match(tabSource, /applyDocPatch/);
	assert.match(tabSource, /Confirm apply/);
});
