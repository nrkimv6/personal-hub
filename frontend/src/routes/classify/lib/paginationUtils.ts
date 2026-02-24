// frontend/src/routes/classify/lib/paginationUtils.ts

export interface PaginationState {
  offset: number;
  limit: number;
  hasMore: boolean;
  total: number;
}

/**
 * 페이지네이션 상태 초기값 생성
 */
export function createPaginationState(limit: number): PaginationState {
  return { offset: 0, limit, hasMore: false, total: 0 };
}

/**
 * 다음 페이지 로드 후 상태 갱신 (반환된 항목 개수 기준)
 */
export function nextPage(state: PaginationState, loadedCount: number): PaginationState {
  return {
    ...state,
    offset: state.offset + loadedCount,
    hasMore: loadedCount === state.limit
  };
}

/**
 * 페이지네이션 상태 초기화 (첫 페이지 로드 전)
 */
export function resetPagination(state: PaginationState): PaginationState {
  return { ...state, offset: 0, hasMore: false, total: 0 };
}

/**
 * URLSearchParams에 skip/limit 파라미터 추가
 */
export function buildPaginationParams(
  state: PaginationState,
  params: URLSearchParams = new URLSearchParams()
): URLSearchParams {
  params.set('skip', String(state.offset));
  params.set('limit', String(state.limit));
  return params;
}
