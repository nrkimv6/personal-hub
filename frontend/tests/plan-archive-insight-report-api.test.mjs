import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiSource = readFileSync(new URL("../src/lib/api/plan-records.ts", import.meta.url), "utf8");
const tabSource = readFileSync(new URL("../src/routes/plans/InsightReportTab.svelte", import.meta.url), "utf8");
const automationSource = readFileSync(new URL("../src/routes/automation/+page.svelte", import.meta.url), "utf8");

test("insight report API wrapper exposes list detail update and promote endpoints", () => {
	assert.match(apiSource, /listInsightReports/);
	assert.match(apiSource, /getInsightReport/);
	assert.match(apiSource, /updateInsightReport/);
	assert.match(apiSource, /promoteInsightPlan/);
	assert.match(apiSource, /\/insights\/reports/);
	assert.match(apiSource, /promote-plan/);
});

test("insight tab component renders report review surface", () => {
	assert.match(tabSource, /Insight reports/);
	assert.match(tabSource, /Root causes/);
	assert.match(tabSource, /Evidence/);
	assert.match(tabSource, /promoteInsightPlan/);
});

test("automation plans subtab includes insights entry", () => {
	assert.match(automationSource, /InsightReportTab/);
	assert.match(automationSource, /subtab=insights|id: 'insights'/);
});
