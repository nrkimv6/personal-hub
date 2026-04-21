/**
 * selection.svelte.ts
 *
 * Svelte 5 $state 기반 Set 통합 선택 유틸리티.
 * 탭별로 중복 구현되던 toggle/selectAll/deselectAll 패턴을 통일한다.
 *
 * ⚠️ `.svelte.ts` 확장자 필수 — $state rune 사용을 위해.
 *
 * 사용 예시:
 *   import { createSelection } from '$lib/utils/selection.svelte';
 *   const selection = createSelection();
 *   // selection.toggle(id), selection.selectAll(ids), selection.count
 *   // Svelte 5: let selection = createSelection(); (rune 없이도 반응형)
 */

export class Selection<T extends string | number = number> {
	ids = $state(new Set<T>());

	/** 선택된 항목 수 */
	get count(): number {
		return this.ids.size;
	}

	/** 주어진 id가 선택됐는지 확인 */
	has(id: T): boolean {
		return this.ids.has(id);
	}

	/** 선택 토글 — 있으면 제거, 없으면 추가 */
	toggle(id: T): void {
		const next = new Set(this.ids);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		this.ids = next; // 재할당으로 Svelte 5 반응형 트리거
	}

	/**
	 * 전체 선택 / 전체 해제 토글.
	 * allIds 목록이 모두 선택돼 있으면 전체 해제, 아니면 전체 선택.
	 */
	selectAll(allIds: T[]): void {
		if (allIds.length === 0) return;

		const allSelected = allIds.every((id) => this.ids.has(id));
		const next = new Set(this.ids);

		if (allSelected) {
			for (const id of allIds) {
				next.delete(id);
			}
		} else {
			for (const id of allIds) {
				next.add(id);
			}
		}

		this.ids = next;
	}

	/** allIds 기준으로 모두 선택됐는지 여부 */
	isAllSelected(allIds: T[]): boolean {
		if (allIds.length === 0) return false;
		return allIds.every((id) => this.ids.has(id));
	}

	/** 선택 전체 해제 */
	deselectAll(): void {
		this.ids = new Set();
	}

	/** 선택 전체 해제 (clear 별칭) */
	clear(): void {
		this.ids = new Set();
	}

	/** API 호출 등에 사용할 배열로 변환 */
	toArray(): T[] {
		return Array.from(this.ids);
	}
}

/**
 * Selection 인스턴스 생성 팩토리 함수.
 * Svelte 5 컴포넌트 내에서 호출하면 $state가 자동으로 반응형으로 동작한다.
 *
 * @example
 * // Svelte 5 컴포넌트
 * const selection = createSelection();
 * // selection.toggle(id) → ids 재할당 → 반응형 업데이트 발생
 */
export function createSelection<T extends string | number = number>(): Selection<T> {
	return new Selection<T>();
}
