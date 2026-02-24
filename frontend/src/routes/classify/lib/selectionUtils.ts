// frontend/src/routes/classify/lib/selectionUtils.ts
//
// classify 탭 공통 선택 유틸리티.
// Svelte 5 $state 기반 구현은 $lib/utils/selection.svelte.ts를 사용하며,
// 이 파일은 classify 모듈에서 편리하게 import하기 위한 re-export + 헬퍼를 제공한다.

export { createSelection, Selection } from '$lib/utils/selection.svelte';

/**
 * 배열 기반 selectedIds와 Set 기반 Selection 간 변환 헬퍼.
 *
 * 기존 `let selectedIds: number[] = $state([])` 패턴에서
 * `createSelection()`으로 마이그레이션 시 사용.
 *
 * @example
 * // 기존 패턴 → 신규 패턴
 * const selection = createSelection();
 * // 배열로 읽기: selection.toArray()
 * // 포함 여부: selection.has(id)
 */
export function arrayToSet(ids: number[]): Set<number> {
  return new Set(ids);
}

export function setToArray(ids: Set<number>): number[] {
  return Array.from(ids);
}
