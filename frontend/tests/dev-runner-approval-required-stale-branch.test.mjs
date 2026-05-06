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
    const devRunnerTab = readSource("src/routes/automation/DevRunnerTab.svelte");

    const instanceGuard = instance.indexOf("if (hideStaleBranchBadge) return null;");
    const instanceBackendLabel = instance.indexOf("return displaySecondary;");
    const statusGuard = statusBar.indexOf("if (runner.hide_stale_branch_badge) return null;");
    const statusBackendLabel = statusBar.indexOf("return runner.display_secondary ?? null;");

    assert.ok(instanceGuard >= 0);
    assert.ok(instanceBackendLabel >= 0);
    assert.ok(instanceGuard < instanceBackendLabel);
    assert.ok(statusGuard >= 0);
    assert.ok(statusBackendLabel >= 0);
    assert.ok(statusGuard < statusBackendLabel);
    assert.match(devRunnerTab, /hideStaleBranchBadge=\{tab\.hide_stale_branch_badge\}/);
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

test("plan claim release uses the same DELETE endpoint through frontend api", () => {
    const api = readSource("src/lib/api/dev-runner.ts");

    assert.match(api, /releaseClaim:\s*\(encodedPath: string\)/);
    assert.match(api, /`\/plans\/\$\{encodedPath\}\/claim`/);
    assert.match(api, /method:\s*'DELETE'/);
});
