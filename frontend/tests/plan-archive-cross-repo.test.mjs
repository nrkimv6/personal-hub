import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const apiSource = readFileSync(new URL("../src/lib/api/plan-records.ts", import.meta.url), "utf8");
const tabSource = readFileSync(new URL("../src/routes/plans/ArchiveTab.svelte", import.meta.url), "utf8");

test("cross repo API wrapper exposes repo filter and index endpoint", () => {
	assert.match(apiSource, /repo_key\?: string/);
	assert.match(apiSource, /PlanArchiveCrossRepoIndexRequest/);
	assert.match(apiSource, /indexCrossRepoArchive/);
	assert.match(apiSource, /\/retrieval\/cross-repo\/index/);
});

test("archive tab does not render cross-repo retrieval controls", () => {
	assert.doesNotMatch(tabSource, /bind:value=\{retrievalRepoKey\}/);
	assert.doesNotMatch(tabSource, /repo_key/);
	assert.doesNotMatch(tabSource, /Cross-repo index/);
	assert.doesNotMatch(tabSource, /cross dry-run/);
	assert.doesNotMatch(tabSource, /Repo evidence/);
	assert.doesNotMatch(tabSource, /Downstream sync evidence/);
});
