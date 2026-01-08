/**
 * 이벤트/팝업 관련 유틸리티 함수
 */

import type { Event, Popup } from '$lib/types';
import { EVENT_STATUS_OPTIONS, URL_TYPE_OPTIONS } from '$lib/constants/eventConstants';

/**
 * 날짜 문자열을 한국어 형식으로 포맷팅
 */
export function formatDate(dateStr: string | null): string {
	if (!dateStr) return '-';
	try {
		const date = new Date(dateStr);
		return date.toLocaleDateString('ko-KR', {
			month: 'short',
			day: 'numeric'
		});
	} catch {
		return '-';
	}
}

/**
 * 이벤트 상태에 따른 배지 색상 클래스 반환
 */
export function getEventStatusColor(status: string): string {
	switch (status) {
		case 'ongoing':
			return 'bg-green-100 text-green-700';
		case 'upcoming':
			return 'bg-blue-100 text-blue-700';
		case 'ended':
			return 'bg-muted text-muted-foreground';
		case 'cancelled':
			return 'bg-red-100 text-red-600';
		default:
			return 'bg-muted text-muted-foreground';
	}
}

/**
 * 이벤트 상태 라벨 반환
 */
export function getEventStatusLabel(status: string): string {
	const option = EVENT_STATUS_OPTIONS.find((o) => o.value === status);
	return option?.label || status;
}

/**
 * URL 타입 라벨 반환
 */
export function getUrlTypeLabel(urlType: string | null): string {
	if (!urlType) return '-';
	const option = URL_TYPE_OPTIONS.find((o) => o.value === urlType);
	return option?.label || urlType;
}

/**
 * D-Day 계산 문자열 반환
 */
export function getDaysRemaining(event: Event): string {
	if (event.days_remaining === null || event.days_remaining === undefined) return '';
	if (event.days_remaining === 0) return 'D-Day';
	if (event.days_remaining > 0) return `D-${event.days_remaining}`;
	return `D+${Math.abs(event.days_remaining)}`;
}

/**
 * 텍스트를 지정된 길이로 자르기
 */
export function truncate(text: string | null, maxLength: number): string {
	if (!text) return '';
	if (text.length <= maxLength) return text;
	return text.slice(0, maxLength) + '...';
}

/**
 * 한국 시간 기준 오늘 날짜 반환 (YYYY-MM-DD)
 */
function getTodayKST(): string {
	return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' });
}

/**
 * 이벤트가 오늘 마감인지 확인 (한국 시간 기준)
 */
export function isEndingToday(event: Event): boolean {
	if (!event.event_end) return false;
	return event.event_end === getTodayKST();
}

/**
 * 이벤트 기간이 미정인지 확인
 */
export function isUnknownPeriod(event: Event): boolean {
	return !event.event_end;
}

/**
 * 팝업이 오늘 마감인지 확인 (한국 시간 기준)
 */
export function isPopupEndingToday(popup: Popup): boolean {
	if (!popup.end_date) return false;
	return popup.end_date === getTodayKST();
}

/**
 * 팝업 기간이 미정인지 확인
 */
export function isPopupUnknownPeriod(popup: Popup): boolean {
	return !popup.end_date;
}

/**
 * 경품 배열을 텍스트로 변환
 */
export function prizesToText(prizes: string[] | undefined): string {
	return (prizes || []).join('\n');
}

/**
 * 텍스트를 경품 배열로 변환
 */
export function textToPrizes(text: string): string[] {
	return text
		.split('\n')
		.map((s) => s.trim())
		.filter((s) => s.length > 0);
}
