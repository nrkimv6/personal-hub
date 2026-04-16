/**
 * 이벤트/팝업 관련 상수
 */

// 이벤트 상태 옵션 (전체 포함)
export const EVENT_STATUS_OPTIONS = [
	{ value: '', label: '전체', color: 'bg-secondary text-foreground' },
	{ value: 'ending_today', label: '오늘 마감', color: 'bg-warning-light text-warning' },
	{ value: 'ongoing', label: '진행 중', color: 'bg-success-light text-success' },
	{ value: 'ongoing_or_upcoming', label: '진행+예정', color: 'bg-sky-100 text-sky-700' },
	{ value: 'upcoming', label: '예정', color: 'bg-primary-light text-primary' },
	{ value: 'ended', label: '종료', color: 'bg-muted text-muted-foreground' },
	{ value: 'cancelled', label: '취소됨', color: 'bg-error-light text-error' }
] as const;

// 기간 미정 필터 옵션
export const UNKNOWN_PERIOD_OPTIONS = [
	{ value: 'exclude', label: '제외', color: 'bg-muted text-muted-foreground' },
	{ value: 'include', label: '포함', color: 'bg-warning-light text-amber-700' },
	{ value: 'only', label: '만', color: 'bg-amber-200 text-amber-800' }
] as const;

// 정렬 옵션
export const SORT_OPTIONS = [
	{ value: 'event_end', label: '마감일' },
	{ value: 'event_start', label: '시작일' },
	{ value: 'created_at', label: '수집일' },
	{ value: 'announcement_date', label: '발표일' }
] as const;

// 출처 유형 옵션
export const SOURCE_TYPE_OPTIONS = [
	{ value: 'instagram', label: '인스타그램' },
	{ value: 'manual', label: '수동등록' },
	{ value: 'web', label: '웹' },
	{ value: 'other', label: '기타' }
] as const;

// 빠른 필터 프리셋
export const QUICK_FILTER_PRESETS = [
	{
		id: 'urgent',
		label: '급한 것 먼저',
		filters: { eventStatus: 'ongoing', sortBy: 'event_end', sortOrder: 'asc', unknownPeriodFilter: 'exclude' }
	},
	{
		id: 'new',
		label: '새로 수집된',
		filters: { eventStatus: '', sortBy: 'created_at', sortOrder: 'desc', unknownPeriodFilter: 'include' }
	},
	{
		id: 'unknown',
		label: '기간미정 정리',
		filters: { eventStatus: '', sortBy: 'created_at', sortOrder: 'desc', unknownPeriodFilter: 'only' }
	}
] as const;

// URL 타입 옵션
export const URL_TYPE_OPTIONS = [
	{ value: 'google_form', label: '구글 폼' },
	{ value: 'naver_form', label: '네이버 폼' },
	{ value: 'shop', label: '쇼핑몰' },
	{ value: 'survey', label: '설문조사' },
	{ value: 'sns', label: 'SNS' },
	{ value: 'other', label: '기타' }
] as const;

// 로컬스토리지 키
export const PARTICIPATED_STORAGE_KEY = 'events_participated';

// 타입 추출
export type EventStatusValue = (typeof EVENT_STATUS_OPTIONS)[number]['value'];
export type UrlTypeValue = (typeof URL_TYPE_OPTIONS)[number]['value'];
export type UnknownPeriodFilterValue = (typeof UNKNOWN_PERIOD_OPTIONS)[number]['value'];
export type SortByValue = (typeof SORT_OPTIONS)[number]['value'];
export type SourceTypeValue = (typeof SOURCE_TYPE_OPTIONS)[number]['value'];
