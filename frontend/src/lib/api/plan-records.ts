/**
 * Plan Records API - 계획서 메타데이터/메모/이력 관리
 */
import { getAuthToken, fetchWithTimeout } from './client';

// ============================================================
// Types
// ============================================================

export interface PlanEvent {
	id: number;
	event_type: string;
	detail: Record<string, unknown> | null;
	created_at: string;
}

export interface PlanRecord {
	id: number;
	filename_hash: string;
	file_path: string;
	project: string | null;
	title: string | null;
	status: string | null;
	memo: string | null;
	memo_draft: string | null;
	archived_at: string | null;
	created_at: string;
	updated_at: string;
	events?: PlanEvent[];
}

// ============================================================
// Internal helper
// ============================================================

async function planRecordsRequest<T>(
	endpoint: string,
	options: RequestInit = {}
): Promise<T> {
	const url = `/api/v1/plans${endpoint}`;

	const token = getAuthToken();
	const headers: HeadersInit = {
		'Content-Type': 'application/json',
		...(token ? { Authorization: `Bearer ${token}` } : {}),
		...options.headers
	};

	const response = await fetchWithTimeout(url, { ...options, headers, credentials: 'include' });

	if (!response.ok) {
		const error = await response.json().catch(() => ({ detail: response.statusText }));
		const detail = error.detail;
		const message = typeof detail === 'string' ? detail : detail?.message || '요청 실패';
		throw new Error(message);
	}

	if (response.status === 204) {
		return null as T;
	}

	return response.json();
}

// ============================================================
// API
// ============================================================

export const planRecordsApi = {
	/**
	 * 레코드 목록 조회
	 */
	list: (params?: { project?: string; status?: string; skip?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.project) q.set('project', params.project);
		if (params?.status) q.set('status', params.status);
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanRecord[]>(`/records${qs ? '?' + qs : ''}`);
	},

	/**
	 * 레코드 상세 조회 (events 포함)
	 */
	get: (id: number) => planRecordsRequest<PlanRecord>(`/records/${id}`),

	/**
	 * file_path로 레코드 get_or_create
	 */
	byPath: (filePath: string) =>
		planRecordsRequest<PlanRecord>(`/records/by-path?file_path=${encodeURIComponent(filePath)}`),

	/**
	 * 메모 업데이트
	 * action: "draft" | "confirm" | "rollback"
	 */
	updateMemo: (id: number, action: 'draft' | 'confirm' | 'rollback', text?: string) =>
		planRecordsRequest<PlanRecord>(`/records/${id}/memo`, {
			method: 'PATCH',
			body: JSON.stringify({ action, text })
		}),

	/**
	 * 수동 동기화 (등록된 경로 전체 스캔)
	 */
	sync: () =>
		planRecordsRequest<{ created: number; updated: number; missing: number }>('/records/sync', {
			method: 'POST'
		}),

	/**
	 * 이벤트 목록 조회 (타임라인용)
	 */
	listEvents: (params?: { event_type?: string; skip?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.event_type) q.set('event_type', params.event_type);
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanEvent[]>(`/events${qs ? '?' + qs : ''}`);
	}
};
