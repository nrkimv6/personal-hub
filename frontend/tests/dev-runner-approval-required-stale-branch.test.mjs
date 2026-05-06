import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

function readSource(path) {
    return readFileSync(resolve(root, path), "utf8");
}

test("approval_required runner hides stale branch badges in detail and status bar", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");
    const statusBar = readSource("src/lib/components/dev-runner/RunStatusBar.svelte");

    const instanceGuard = instance.indexOf("if (mergeStatus === 'approval_required') return null;");
    const instanceBranchLabel = instance.indexOf("if (branchExists === false) return 'branch 없음';");
    const statusGuard = statusBar.indexOf("if (runner.merge_status === 'approval_required') return null;");
    const statusBranchLabel = statusBar.indexOf("if (runner.branch_exists === false) return 'branch 없음';");

    assert.ok(instanceGuard >= 0);
    assert.ok(instanceBranchLabel >= 0);
    assert.ok(instanceGuard < instanceBranchLabel);
    assert.ok(statusGuard >= 0);
    assert.ok(statusBranchLabel >= 0);
    assert.ok(statusGuard < statusBranchLabel);
    assert.match(instance, /mergeStatus !== 'approval_required' && branchExists === false/);
});

test("service lock approval button sends one-shot approve_service_lock retry payload", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    assert.match(instance, /async function handleApproveServiceLockAndRetryMerge\(\)/);
    assert.match(instance, /approve_service_lock:\s*true/);
    assert.match(instance, /경고 확인 후 머지/);
});

test("merge_status error takes precedence over completed lifecycle labels", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");
    const statusBar = readSource("src/lib/components/dev-runner/RunStatusBar.svelte");

    const instanceError = instance.indexOf("if (mergeStatusValue === 'error') return '머지 오류';");
    const instanceFallback = instance.indexOf("return getExitReasonDisplay(exitReasonValue).statusIcon;");
    const statusError = statusBar.indexOf("if (runner.merge_status === 'error') return '머지 오류';");
    const statusFallback = statusBar.indexOf("const exitDisplay = getExitReasonDisplay(runner.exit_reason);");

    assert.ok(instanceError >= 0);
    assert.ok(instanceFallback >= 0);
    assert.ok(instanceError < instanceFallback);
    assert.ok(statusError >= 0);
    assert.ok(statusFallback >= 0);
    assert.ok(statusError < statusFallback);
});
