import test from "node:test";
import assert from "node:assert/strict";
import { isStartOnlyRecentLog } from "../src/lib/dev-runner/log-recent-fallback.js";

test("START-only recent log is detected for full fallback", () => {
	assert.equal(
		isStartOnlyRecentLog([
			"[2026-05-04T16:48:10] START | log_path=plan-runner-d31509ad-20260504-164804.log",
		]),
		true,
	);
});

test("plan start marker only recent log is detected for full fallback", () => {
	assert.equal(isStartOnlyRecentLog(["[plan:d31509ad start]"]), true);
});

test("real plan-runner output does not trigger full fallback", () => {
	assert.equal(
		isStartOnlyRecentLog([
			"[16:48:15] [PLAN-RUNNER#feat-mp4@d315] [ERROR] pre-write scope gate failed",
			"WRITE_SCOPE_REROUTE_REQUIRED:target_path=...",
		]),
		false,
	);
});
