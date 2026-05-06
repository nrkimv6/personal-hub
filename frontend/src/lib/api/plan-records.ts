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
	category: string | null;
	tags: string[] | null;
	summary: string | null;
	superseded_by: string | null;
	recurrence_count: number;
	chain_root_hash: string | null;
	recurrence_suggestion: string | null;
	intent: string | null;
	trigger: string | null;
	scope: string[] | null;
	plan_date: string | null;
	applied_at: string | null;
	llm_processed_at: string | null;
	created_at: string;
	updated_at: string;
	events?: PlanEvent[];
	applied_request_id?: number | null;
}

export interface SyncResult {
	created: number;
	updated: number;
	missing: number;
	archive_created: number;
	archive_updated: number;
	archive_normalized: number;
}

export interface ImportArchivedResult {
	created: number;
	updated: number;
	skipped: number;
	errors: string[];
}

export interface ArchiveCandidate {
	filename_hash: string;
	file_path: string;
	file_exists: boolean;
	db_exists: boolean;
	state: string;
	reason: string;
	eligible_for_import: boolean;
	eligible_for_analysis: boolean;
	registered_path: string | null;
	duplicate_paths: string[];
	file_mtime: string | null;
	file_size: number | null;
	record: PlanRecord | null;
}

export interface ArchiveCandidateSummary {
	total: number;
	returned: number;
	file_only: number;
	db_only: number;
	matched: number;
	needs_archive_normalization: number;
	stale_path: number;
	duplicate_hash: number;
	llm_pending: number;
	candidates: ArchiveCandidate[];
}

export interface ArchiveAnalyzeRequest {
	provider?: string | null;
	model?: string | null;
	profile_key?: string | null;
}

export interface ArchiveAnalyzeResponse {
	id: number;
	caller_type: string;
	caller_id: string;
	status: string;
	provider: string;
	model: string;
	profile_key: string | null;
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
	list: (params?: {
		project?: string;
		status?: string;
		category?: string;
		tags?: string;
		skip?: number;
		limit?: number;
	}) => {
		const q = new URLSearchParams();
		if (params?.project) q.set('project', params.project);
		if (params?.status) q.set('status', params.status);
		if (params?.category) q.set('category', params.category);
		if (params?.tags) q.set('tags', params.tags);
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
		planRecordsRequest<SyncResult>('/records/sync', {
			method: 'POST'
		}),

	/**
	 * archive 파일 + DB 실행 후보 목록
	 */
	listArchiveCandidates: (params?: { include_temp?: boolean; skip?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.include_temp != null) q.set('include_temp', String(params.include_temp));
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<ArchiveCandidateSummary>(`/records/archive-candidates${qs ? '?' + qs : ''}`);
	},

	/**
	 * archived record를 plan_archive_analyze LLM 큐에 등록
	 */
	queueArchiveAnalyze: (recordId: number, data: ArchiveAnalyzeRequest) =>
		planRecordsRequest<ArchiveAnalyzeResponse>(`/records/archive-analyze/${recordId}`, {
			method: 'POST',
			body: JSON.stringify(data)
		}),

	/**
	 * archived plan 일괄 DB 이관
	 */
	importArchived: (archiveDir?: string) =>
		planRecordsRequest<ImportArchivedResult>(
			`/records/import-archived${archiveDir ? '?archive_dir=' + encodeURIComponent(archiveDir) : ''}`,
			{ method: 'POST' }
		),

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
	},

	/**
	 * 체인 조회 — chain_root_hash 기준 반복 이력 목록
	 */
	getChain: (recordId: number) =>
		planRecordsRequest<PlanRecord[]>(`/records/${recordId}/chain`),

	/**
	 * 반복 수정 통계
	 */
	getRecurrenceStatistics: () =>
		planRecordsRequest<{
			by_category: Record<string, number>;
			top_scopes: string[];
			total_recurrences: number;
		}>('/statistics/recurrence'),

	/**
	 * archive record LLM 재분석 요청 큐 등록
	 * profile_key 없는 provider(codex 등) 허용
	 */
	reanalyze: (recordId: number, payload: { provider: string; model?: string; profile_key?: string | null }) =>
		planRecordsRequest<{ queued: boolean; request_id: number; provider: string; model: string }>(
			`/records/${recordId}/reanalyze`,
			{
				method: 'POST',
				body: JSON.stringify({ provider: payload.provider, model: payload.model ?? '', profile_key: payload.profile_key ?? null })
			}
		),

	/**
	 * 레코드 목록 (recurrence_count 필터용, listRecords alias)
	 */
	listRecords: (params?: { skip?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanRecord[]>(`/records${qs ? '?' + qs : ''}`);
	},

	/**
	 * LLM request caller_id(filename_hash)로 연결된 PlanRecord 조회 helper
	 * candidate list에서 먼저 찾고 없으면 archived 목록 전체 검색
	 */
	findRecordByHash: async (
		filename_hash: string,
		hint_records?: PlanRecord[]
	): Promise<PlanRecord | null> => {
		if (hint_records) {
			const found = hint_records.find(r => r.filename_hash === filename_hash);
			if (found) return found;
		}
		// fallback: archived 목록 조회
		const all = await planRecordsRequest<PlanRecord[]>('/records?status=archived&limit=500');
		return all.find(r => r.filename_hash === filename_hash) ?? null;
	}
};

// ============================================================
// Archive 정리 API
// ============================================================

export interface ArchivePreviewItem {
	source: string;
	dest: string;
	filename: string;
	category: string;
	needs_move: boolean;
}

export interface ArchivePreviewDir {
	archive_dir: string;
	items: ArchivePreviewItem[];
}

export interface ArchivePreviewResult {
	dirs: ArchivePreviewDir[];
	message?: string;
}

export interface ArchiveOrganizeResult {
	results: Array<{
		archive_dir: string;
		moved: Array<{ source: string; dest: string }>;
		skipped: number;
		errors: Array<{ source: string; error: string }>;
		removed_dirs: string[];
	}>;
	message?: string;
}

export interface DuplicateItem {
	file_a: string;
	file_b: string;
	similarity: number;
	reason: 'exact_name' | 'similar_name';
}

export interface DuplicatesResult {
	dirs: Array<{ archive_dir: string; duplicates: DuplicateItem[] }>;
	message?: string;
}

async function devRunnerRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
	const { getAuthToken, fetchWithTimeout } = await import('./client');
	const url = `/api/v1/dev-runner${endpoint}`;
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
	return response.json();
}

export const archiveApi = {
	/**
	 * archive 폴더 정리 미리보기
	 */
	preview: () => devRunnerRequest<ArchivePreviewResult>('/plans/archive/preview'),

	/**
	 * archive 폴더 정리 실행 (파일 이동 + DB 업데이트)
	 */
	organize: (archive_dir?: string) =>
		devRunnerRequest<ArchiveOrganizeResult>('/plans/archive/organize', {
			method: 'POST',
			body: JSON.stringify(archive_dir ? { archive_dir } : {})
		}),

	/**
	 * 중복 파일 감지
	 */
	duplicates: (similarity?: number) => {
		const q = similarity != null ? `?similarity=${similarity}` : '';
		return devRunnerRequest<DuplicatesResult>(`/plans/archive/duplicates${q}`);
	}
};
