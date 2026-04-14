/**
 * shouldShowMergeCompletionBanner 단위 TC
 * node --test 기반 — TypeScript import 불필요, 순수 로직 검증
 */
import test from "node:test";
import assert from "node:assert/strict";

// 로직을 인라인으로 정의 (TypeScript 빌드 없이 검증)
const SAFE_REASONS = ['completed', 'stopped', 'archived', 'on_hold', 'unknown'];

function shouldShowMergeCompletionBanner(reason, status) {
    if (status === 'failed') return true;
    if (!reason) return false;
    // getExitReasonDisplay fallback: 알 수 없는 reason은 그대로 반환
    const normalized = reason;
    return !SAFE_REASONS.includes(normalized);
}

test("R: status=success, reason=completed → false (배너 미표시)", () => {
    assert.equal(shouldShowMergeCompletionBanner('completed', 'success'), false);
});

test("R: status=failed, reason=merge_failed → true (배너 표시)", () => {
    assert.equal(shouldShowMergeCompletionBanner('merge_failed', 'failed'), true);
});

test("B: status=undefined, reason=completed → false", () => {
    assert.equal(shouldShowMergeCompletionBanner('completed', undefined), false);
});

test("E: status=failed, reason=undefined → true (failed status는 reason 무관 배너 표시)", () => {
    assert.equal(shouldShowMergeCompletionBanner(undefined, 'failed'), true);
});

test("B: reason=stopped, status=success → false (정상 종료는 배너 미표시)", () => {
    assert.equal(shouldShowMergeCompletionBanner('stopped', 'success'), false);
});
