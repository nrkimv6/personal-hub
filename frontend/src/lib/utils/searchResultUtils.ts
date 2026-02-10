/**
 * 검색결과 관리 유틸리티 함수
 */
import { RANK_CHANGE_STYLES } from '../constants/searchResultConstants';
import type { SearchResultListItem } from '../types';

/**
 * 순위 변화에 따른 스타일 정보 반환
 */
export function getRankChangeStyle(item: SearchResultListItem) {
	if (item.is_new) {
		return RANK_CHANGE_STYLES.new;
	}
	if (item.rank_change === null || item.rank_change === undefined) {
		return RANK_CHANGE_STYLES.same;
	}
	if (item.rank_change > 0) {
		return RANK_CHANGE_STYLES.up;
	}
	if (item.rank_change < 0) {
		return RANK_CHANGE_STYLES.down;
	}
	return RANK_CHANGE_STYLES.same;
}

/**
 * 순위 변화 텍스트 포맷
 */
export function formatRankChange(item: SearchResultListItem): string {
	if (item.is_new) {
		return 'NEW';
	}
	if (item.rank_change === null || item.rank_change === undefined) {
		return '─';
	}
	if (item.rank_change > 0) {
		return `▲${item.rank_change}`;
	}
	if (item.rank_change < 0) {
		return `▼${Math.abs(item.rank_change)}`;
	}
	return '─';
}

/**
 * URL에서 도메인 추출
 */
export function extractDomain(url: string): string {
	try {
		const urlObj = new URL(url);
		return urlObj.hostname;
	} catch {
		return url;
	}
}

/**
 * 스니펫 텍스트 줄이기
 */
export function truncateSnippet(snippet: string | null, maxLength: number = 100): string {
	if (!snippet) return '';
	if (snippet.length <= maxLength) return snippet;
	return snippet.substring(0, maxLength) + '...';
}

/**
 * 날짜 포맷 (상대적 시간)
 */
export function formatRelativeDate(dateString: string): string {
	const date = new Date(dateString);
	const now = new Date();
	const diffMs = now.getTime() - date.getTime();
	const diffMins = Math.floor(diffMs / 60000);
	const diffHours = Math.floor(diffMs / 3600000);
	const diffDays = Math.floor(diffMs / 86400000);

	if (diffMins < 1) return '방금 전';
	if (diffMins < 60) return `${diffMins}분 전`;
	if (diffHours < 24) return `${diffHours}시간 전`;
	if (diffDays < 7) return `${diffDays}일 전`;

	return date.toLocaleDateString('ko-KR', {
		year: 'numeric',
		month: 'short',
		day: 'numeric'
	});
}

/**
 * 날짜 포맷 (YYYY-MM-DD)
 */
export function formatDate(dateString: string | null): string {
	if (!dateString) return '-';
	const date = new Date(dateString);
	return date.toLocaleDateString('ko-KR', {
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	});
}

/**
 * 결과 행 스타일 클래스 생성
 */
export function getRowClasses(item: SearchResultListItem): string {
	const classes: string[] = [];

	if (item.is_new) {
		classes.push('border-l-4 border-l-blue-500 bg-blue-50/30');
	}

	if (item.is_read) {
		classes.push('opacity-60');
	}

	return classes.join(' ');
}
