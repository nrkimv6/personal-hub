/**
 * 이벤트/팝업 관련 상수
 */

// 이벤트 상태 옵션
export const EVENT_STATUS_OPTIONS = [
	{ value: 'ending_today', label: '오늘 마감', color: 'bg-orange-100 text-orange-700' },
	{ value: 'ongoing', label: '진행 중', color: 'bg-green-100 text-green-700' },
	{ value: 'upcoming', label: '예정', color: 'bg-blue-100 text-blue-700' },
	{ value: 'ended', label: '종료', color: 'bg-gray-100 text-gray-600' },
	{ value: 'cancelled', label: '취소됨', color: 'bg-red-100 text-red-600' }
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
