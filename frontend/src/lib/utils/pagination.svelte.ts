/**
 * pagination.svelte.ts
 *
 * Svelte 5 $state 기반 페이지네이션 유틸리티.
 * 탭별로 중복 구현되던 offset/page 패턴을 통일한다.
 *
 * ⚠️ `.svelte.ts` 확장자 필수 — $state/$derived rune 사용을 위해.
 *
 * 사용 예시:
 *   import { createOffsetPagination, createPagePagination } from '$lib/utils/pagination.svelte';
 *   const pager = createOffsetPagination(24);
 *   // pager.toParams() → { skip: "0", limit: "24" }
 *   // pager.advance(loaded, total), pager.reset()
 */

// ──────────────────────────────────────────────
// Offset 기반 (더 보기 / 무한스크롤 패턴)
// ──────────────────────────────────────────────

export class OffsetPagination {
	offset = $state(0);
	limit: number;
	hasMore = $state(false);
	total = $state(0);

	constructor(limit: number) {
		this.limit = limit;
	}

	/** 첫 페이지로 리셋 */
	reset(): void {
		this.offset = 0;
		this.hasMore = false;
		this.total = 0;
	}

	/**
	 * 로드 완료 후 상태 갱신.
	 * @param loadedCount 이번 요청에서 받은 항목 수
	 * @param totalCount 서버가 반환한 전체 항목 수
	 */
	advance(loadedCount: number, totalCount: number): void {
		this.offset += loadedCount;
		this.total = totalCount;
		this.hasMore = this.offset < totalCount;
	}

	/** API 쿼리 파라미터로 변환 */
	toParams(): Record<string, string> {
		return {
			skip: String(this.offset),
			limit: String(this.limit)
		};
	}
}

/**
 * OffsetPagination 인스턴스 생성 팩토리 함수.
 * @param limit 한 번에 불러올 항목 수
 */
export function createOffsetPagination(limit: number): OffsetPagination {
	return new OffsetPagination(limit);
}

// ──────────────────────────────────────────────
// Page 번호 기반 (페이지 네비게이션 패턴)
// ──────────────────────────────────────────────

export class PagePagination {
	page = $state(1);
	pageSize: number;
	total = $state(0);
	totalPages = $derived.by(() => Math.max(1, Math.ceil(this.total / this.pageSize)));

	constructor(pageSize: number) {
		this.pageSize = pageSize;
	}

	/** 1페이지로 리셋 */
	reset(): void {
		this.page = 1;
		this.total = 0;
	}

	/** 특정 페이지로 이동 (범위 밖이면 무시) */
	goTo(page: number): void {
		if (page < 1 || page > this.totalPages) return;
		this.page = page;
	}

	/** 이전 페이지 (1페이지 미만이면 무시) */
	prev(): void {
		if (this.page > 1) this.page--;
	}

	/** 다음 페이지 (마지막 페이지 초과이면 무시) */
	next(): void {
		if (this.page < this.totalPages) this.page++;
	}

	/** API 쿼리 파라미터로 변환 (skip/limit) */
	toParams(): Record<string, string> {
		return {
			skip: String((this.page - 1) * this.pageSize),
			limit: String(this.pageSize)
		};
	}
}

/**
 * PagePagination 인스턴스 생성 팩토리 함수.
 * @param pageSize 페이지당 항목 수
 */
export function createPagePagination(pageSize: number): PagePagination {
	return new PagePagination(pageSize);
}
