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
    // 버튼 label: 위험 확인 후 머지 재시도 (one-shot runner/worktree retry 의미)
    assert.match(instance, /위험 확인 후 머지 재시도/);
});

test("service lock approval banner uses 실행 중 서비스와 겹치는 변경이라 승인 필요 wording", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // 문구 계약: 사용자가 무엇을 승인하는지 즉시 이해할 수 있게 한다
    assert.match(instance, /실행 중 서비스와 겹치는 변경이라 승인 필요/);
});

test("service lock approval button title and aria-label describe one-shot retry meaning", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // title: approve_service_lock one-shot override 의미가 담겨야 한다
    assert.match(instance, /approve_service_lock one-shot override/);
    // aria-label: 접근성 — 재시도 의미 명시
    assert.match(instance, /aria-label/);
    assert.match(instance, /머지 재시도/);
});

test("service lock approval button is disabled while retryingMerge to prevent double-click", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // approval 버튼은 retryingMerge 중 disabled 처리
    const approvalSection = instance.slice(
        instance.indexOf("approval_required"),
        instance.indexOf("conflict', 'test_failed', 'error'")
    );
    assert.match(approvalSection, /disabled=\{retryingMerge\}/);
    // 진행 중 상태 문구 구체화
    assert.match(approvalSection, /승인 후 재시도 중/);
});

test("service lock approval section shows changed and running evidence from gateEvidenceSummary", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // gateEvidenceSummary.changed 와 gateEvidenceSummary.running을 evidence로 표시
    assert.match(instance, /gateEvidenceSummary\?\.changed/);
    assert.match(instance, /gateEvidenceSummary\?\.running/);
    // 변경/실행 중 레이블 표시
    assert.match(instance, /변경:/);
    assert.match(instance, /실행 중:/);
});

test("worktree cleanup button title clarifies it is not a merge retry in approval_required", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // approval_required 섹션 내 Worktree 정리 버튼 title
    const approvalSection = instance.slice(
        instance.indexOf("approval_required"),
        instance.indexOf("conflict', 'test_failed', 'error'")
    );
    // title에 '머지 재시도가 아닌' 또는 '취소' 또는 '정리'가 포함되어야 한다
    assert.match(approvalSection, /머지 재시도가 아닌|취소|Worktree 정리 \(취소\)/);
    assert.match(approvalSection, /Worktree 정리/);
});

test("status bar shows 승인 필요 · service_lock badge for approval_required runners", () => {
    const statusBar = readSource("src/lib/components/dev-runner/RunStatusBar.svelte");

    // approval_required 상태에서 '승인 필요'와 'service_lock' 문자열이 함께 표시
    assert.match(statusBar, /승인 필요.*service_lock|service_lock.*승인 필요/);
    // 조건 분기: approval_required에서 해당 badge를 표시
    assert.match(statusBar, /runner\.merge_status === 'approval_required'/);
});

test("GateEvidenceSummary type declares changed and running fields for service_lock evidence", () => {
    const api = readSource("src/lib/api/dev-runner.ts");

    // changed/running 필드가 타입에 명시적으로 선언되어 있어야 한다
    assert.match(api, /changed\?:\s*string\[\]\s*\|\s*null/);
    assert.match(api, /running\?:\s*string\[\]\s*\|\s*null/);
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

test("approval_required banner shows '자동 수정 대상 아님' label (not a code defect)", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // service_lock은 자동 수정 대상 아님을 사용자에게 명시해야 함
    assert.match(instance, /자동 수정 대상 아님/,
        "approval_required 배너에 '자동 수정 대상 아님' 문구가 없음");
});

test("approval_required banner shows rebase_failed notice when merge_message includes [rebase_failed", () => {
    const instance = readSource("src/lib/components/dev-runner/RunnerInstanceTab.svelte");

    // rebase 실패 결합 케이스 표시 로직이 있어야 함
    assert.match(instance, /rebase_failed/,
        "approval_required 배너에 rebase_failed 결합 케이스 처리 로직 없음");
    assert.match(instance, /rebase 충돌도 함께 발생/,
        "approval_required 배너에 rebase 충돌 안내 문구 없음");
});
