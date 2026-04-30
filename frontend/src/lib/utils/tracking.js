export const TRACKING_FILTERS = ['all', 'overdue', 'ready', 'upcoming', 'done'];

/** @typedef {import('$lib/api/tracking').TrackingItem} TrackingItem */

/**
 * @param {string | null | undefined} status
 * @returns {string}
 */
export function getTrackingStatusLabel(status) {
	switch (status) {
		case 'done':
			return '완료';
		case 'overdue':
			return '지연';
		case 'ready':
			return '준비됨';
		case 'upcoming':
			return '예정';
		default:
			return status || '알 수 없음';
	}
}

/**
 * @param {string | null | undefined} status
 * @returns {string}
 */
export function getTrackingStatusClass(status) {
	switch (status) {
		case 'done':
			return 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
		case 'overdue':
			return 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300';
		case 'ready':
			return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300';
		case 'upcoming':
			return 'bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300';
		default:
			return 'bg-muted text-muted-foreground';
	}
}

/**
 * @param {{ title?: unknown; description?: unknown; start_at?: string | null; due_at?: string | null }} form
 * @returns {{ title: string; description: string | null; start_at: string | null; due_at: string | null }}
 */
export function buildTrackingPayload(form) {
	const payload = {
		title: String(form.title || '').trim(),
		description: String(form.description || '').trim() || null,
		start_at: form.start_at || null,
		due_at: form.due_at || null,
	};
	if (!payload.title) {
		throw new Error('제목을 입력하세요.');
	}
	if (!payload.start_at && !payload.due_at) {
		throw new Error('시작가능일 또는 마감기한 중 하나 이상을 입력하세요.');
	}
	return payload;
}

/**
 * @param {string | null | undefined} value
 * @returns {number}
 */
function itemDateValue(value) {
	if (!value) return Number.POSITIVE_INFINITY;
	const time = new Date(value).getTime();
	return Number.isNaN(time) ? Number.POSITIVE_INFINITY : time;
}

/**
 * @param {TrackingItem[]} items
 * @returns {TrackingItem[]}
 */
export function sortTrackingItems(items) {
	const statusRank = /** @type {Record<string, number>} */ ({ overdue: 0, ready: 1, upcoming: 2, done: 3 });
	return [...items].sort((a, b) => {
		if (a.status === 'done' || b.status === 'done') {
			if (a.status !== b.status) return a.status === 'done' ? 1 : -1;
			return itemDateValue(b.completed_at) - itemDateValue(a.completed_at);
		}
		const rankDiff = statusRank[a.status] - statusRank[b.status];
		if (rankDiff !== 0) return rankDiff;
		return itemDateValue(a.due_at || a.start_at) - itemDateValue(b.due_at || b.start_at);
	});
}
