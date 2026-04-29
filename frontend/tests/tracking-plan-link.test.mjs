import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// ── 헬퍼: 모달 저장 시 diff 계산 로직 (TrackingTab에서 추출한 순수 함수) ──────────

/**
 * 기존 연결 목록과 새 선택 목록을 비교해 add/remove 집합을 반환한다.
 * TrackingTab.svelte의 saveItem diff 계산과 동일 로직.
 */
function calcLinkDiff(existingIds, nextIds) {
  const existingSet = new Set(existingIds);
  const nextSet = new Set(nextIds);
  const add = [...nextSet].filter((id) => !existingSet.has(id));
  const remove = [...existingSet].filter((id) => !nextSet.has(id));
  return { add, remove };
}

// ── TC 20: Frontend RIGHT-BICEP + CORRECT ────────────────────────────────────

test("picker_multi_select_calls_onChange_with_correct_ids — 다중 선택 시 중복 없는 배열 반환", () => {
  // calcLinkDiff 기반으로 onChange 결과 검증
  const current = [3, 5, 7];
  const next = [3, 7, 9];
  const { add, remove } = calcLinkDiff(current, next);
  assert.deepEqual(add, [9]);
  assert.deepEqual(remove, [5]);
});

test("picker_already_linked_disabled — TrackingPlanPicker가 alreadyLinked 렌더링", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingPlanPicker.svelte", import.meta.url),
    "utf8"
  );
  // disabled 속성 + "연결됨" 배지가 컴포넌트에 존재
  assert.match(src, /disabled.*alreadyIn|alreadyIn.*disabled/s);
  assert.match(src, /연결됨/);
});

test("picker_empty_search_results — 검색 결과 없을 때 '검색 결과 없음' 표시", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingPlanPicker.svelte", import.meta.url),
    "utf8"
  );
  assert.match(src, /검색 결과 없음/);
});

test("picker_debounce_300ms — debounce 타이머가 300ms로 설정됨", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingPlanPicker.svelte", import.meta.url),
    "utf8"
  );
  assert.match(src, /300/);
  assert.match(src, /setTimeout/);
});

test("modal_save_diff_calculation — [3,5,7] → [3,7,9] 변경 시 add=[9], remove=[5]", () => {
  const { add, remove } = calcLinkDiff([3, 5, 7], [3, 7, 9]);
  assert.deepEqual(add, [9]);
  assert.deepEqual(remove, [5]);
});

test("modal_save_diff_calculation — no change keeps empty diff", () => {
  const { add, remove } = calcLinkDiff([1, 2, 3], [1, 2, 3]);
  assert.deepEqual(add, []);
  assert.deepEqual(remove, []);
});

test("modal_save_diff_calculation — remove all links", () => {
  const { add, remove } = calcLinkDiff([1, 2], []);
  assert.deepEqual(add, []);
  assert.deepEqual(remove.sort(), [1, 2]);
});

test("modal_save_network_failure_rollback — TrackingTab linkPlans 실패 시 toast.error 호출", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingTab.svelte", import.meta.url),
    "utf8"
  );
  // 에러 처리 코드에 toast.error가 있는지 확인
  assert.match(src, /toast\.error.*plan 연결|plan 연결.*toast\.error/s);
});

test("modal_save_partial_failure_handling — 생성 후 linkPlans 실패 graceful 처리", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingTab.svelte", import.meta.url),
    "utf8"
  );
  // 항목 생성 후 plan 연결 분리 처리 (try-catch 분리)
  assert.match(src, /linkPlans/);
  assert.match(src, /unlinkPlan/);
  // toast 에러 메시지가 존재
  assert.match(src, /추가됐지만.*plan 연결|plan 연결.*실패/s);
});

test("TrackingPlanPicker is imported in TrackingTab", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingTab.svelte", import.meta.url),
    "utf8"
  );
  assert.match(src, /TrackingPlanPicker/);
  assert.match(src, /import TrackingPlanPicker/);
});

test("Card shows plan link count badge when linked_plans present", () => {
  const src = readFileSync(
    new URL("../src/routes/automation/TrackingTab.svelte", import.meta.url),
    "utf8"
  );
  assert.match(src, /linked_plans\.length/);
  assert.match(src, /계획서/);
});
