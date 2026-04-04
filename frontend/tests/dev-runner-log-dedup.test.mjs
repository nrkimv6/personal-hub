import test from "node:test";
import assert from "node:assert/strict";
import { lineFingerprint, shouldSkipInjectedLine } from "../src/lib/dev-runner/log-dedup.js";

test("same runner same line is deduped on second injection", () => {
	const cache = new Map();
	assert.equal(shouldSkipInjectedLine(cache, "runner-a", "hello"), false);
	assert.equal(shouldSkipInjectedLine(cache, "runner-a", "hello"), true);
});

test("same runner mixed log channels still dedup by identical line", () => {
	const cache = new Map();
	const sameLine = "[MERGE] done";
	assert.equal(shouldSkipInjectedLine(cache, "runner-b", sameLine), false);
	assert.equal(shouldSkipInjectedLine(cache, "runner-b", sameLine), true);
});

test("different runners do not share dedup fingerprints", () => {
	const cache = new Map();
	assert.equal(shouldSkipInjectedLine(cache, "runner-c1", "shared line"), false);
	assert.equal(shouldSkipInjectedLine(cache, "runner-c2", "shared line"), false);
});

test("fingerprint changes when runner id changes", () => {
	const line = "same-content";
	assert.notEqual(
		lineFingerprint("runner-d1", line),
		lineFingerprint("runner-d2", line),
	);
});
