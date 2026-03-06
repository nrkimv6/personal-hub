/**
 * 검색결과 관리 관련 상수
 */

// 빠른 필터 탭 옵션
export const RESULT_FILTER_TABS = [
	{ value: 'all', label: '전체' },
	{ value: 'new', label: '신규만' },
	{ value: 'bookmarked', label: '북마크' },
	{ value: 'disappeared', label: '사라진 결과' }
] as const;

// 정렬 옵션
export const RESULT_SORT_OPTIONS = [
	{ value: 'created_at', label: '수집일', defaultOrder: 'desc' },
	{ value: 'rank', label: '순위', defaultOrder: 'asc' },
	{ value: 'rank_change', label: '순위 변화', defaultOrder: 'desc' },
	{ value: 'query', label: '검색어', defaultOrder: 'asc' },
	{ value: 'publish_date', label: '게시일', defaultOrder: 'desc' }
] as const;

// 읽음 필터 옵션
export const READ_FILTER_OPTIONS = [
	{ value: '', label: '전체' },
	{ value: 'false', label: '읽지 않음' },
	{ value: 'true', label: '읽음' }
] as const;

// 페이지 크기 옵션
export const PAGE_SIZE_OPTIONS = [
	{ value: 10, label: '10개씩' },
	{ value: 20, label: '20개씩' },
	{ value: 50, label: '50개씩' },
	{ value: 100, label: '100개씩' }
] as const;

// 순위 변화 표시 스타일
export const RANK_CHANGE_STYLES = {
	up: { icon: '▲', color: 'text-green-600', bg: 'bg-green-50' },
	down: { icon: '▼', color: 'text-red-600', bg: 'bg-red-50' },
	same: { icon: '─', color: 'text-gray-400', bg: '' },
	new: { icon: 'NEW', color: 'text-blue-600', bg: 'bg-blue-50' }
} as const;

// 타입 추출
export type ResultFilterTabValue = (typeof RESULT_FILTER_TABS)[number]['value'];
export type ResultSortByValue = (typeof RESULT_SORT_OPTIONS)[number]['value'];
export type ReadFilterValue = (typeof READ_FILTER_OPTIONS)[number]['value'];
