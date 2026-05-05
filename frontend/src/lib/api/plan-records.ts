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
	llm_processed_at: string | null;
	file_delete_after: string | null;
	file_removed_at: string | null;
	created_at: string;
	updated_at: string;
	events?: PlanEvent[];
}

export interface ImportArchivedResult {
	created: number;
	updated: number;
	skipped: number;
	errors: string[];
}

export interface PlanArchiveHealth {
	archived_total: number;
	llm_processed: number;
	llm_unprocessed: number;
	real_unprocessed: number;
	temp_pytest_total: number;
	temp_pytest_unprocessed: number;
	pending_or_processing_requests: number;
	failed_requests: number;
	file_retention_due: number;
	file_retention_scheduled: number;
	file_removed: number;
	oldest_file_delete_after: string | null;
	latest_failed_request: {
		id: number;
		caller_id: string;
		requested_at: string | null;
		error_message: string | null;
	} | null;
	oldest_unprocessed_at: string | null;
	plan_archive_schedule: {
		id: number;
		enabled: boolean;
		schedule_value: string | null;
		last_run: string | null;
		last_success: string | null;
		last_failure: string | null;
	} | null;
}

export interface PlanArchiveRetrievalQuery {
	q?: string;
	date_from?: string;
	date_to?: string;
	category?: string;
	tags?: string[];
	intent?: string;
	scope?: string;
	path?: string;
	relation_type?: string;
	limit?: number;
}

export interface PlanArchiveChunkHit {
	id: number;
	section_type?: string;
	heading?: string;
	text: string;
	snippet?: string;
	score?: number;
}

export interface PlanArchiveFileRefHit {
	id: number;
	path: string;
	source_type: string;
	module?: string;
	commit_sha?: string;
	exists_at_index?: boolean;
}

export interface PlanArchiveRetrievalResult {
	plan: PlanRecord | Record<string, unknown>;
	score: number;
	score_detail: Record<string, unknown>;
	chunks: PlanArchiveChunkHit[];
	file_refs: PlanArchiveFileRefHit[];
}

export interface PlanArchiveRetrievalResponse {
	results: PlanArchiveRetrievalResult[];
	total: number;
}

export interface PlanArchiveMetricsResponse {
	total_plans: number;
	followup_rates: {
		days_7: number;
		days_14: number;
		days_30: number;
	};
	top_file_refs: Array<{
		path: string;
		count: number;
		mentioned_count: number;
		changed_count: number;
	}>;
	missing_file_candidates: Array<{
		module: string;
		count: number;
		paths: string[];
	}>;
	relation_counts: Record<string, number>;
	chain_depth_max: number;
}

export interface PlanArchiveIndexRequest {
	limit?: number;
	force?: boolean;
	since?: string;
	apply?: boolean;
}

export interface PlanArchiveIndexResponse {
	dry_run: boolean;
	indexed: number;
	failed: number;
	skipped: number;
	run_id?: number | null;
	errors?: string[];
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
		q?: string;
		deep?: boolean;
		include_temp?: boolean;
	}) => {
		const q = new URLSearchParams();
		if (params?.project) q.set('project', params.project);
		if (params?.status) q.set('status', params.status);
		if (params?.category) q.set('category', params.category);
		if (params?.tags) q.set('tags', params.tags);
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		if (params?.q) q.set('q', params.q);
		if (params?.deep !== undefined) q.set('deep', String(params.deep));
		if (params?.include_temp !== undefined) q.set('include_temp', String(params.include_temp));
		const qs = q.toString();
		return planRecordsRequest<PlanRecord[]>(`/records${qs ? '?' + qs : ''}`);
	},

	getArchiveHealth: (includeTemp = false) =>
		planRecordsRequest<PlanArchiveHealth>(`/records/archive-health?include_temp=${includeTemp}`),

	searchArchiveRetrieval: (payload: PlanArchiveRetrievalQuery) =>
		planRecordsRequest<PlanArchiveRetrievalResponse>('/retrieval/search', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	getArchiveRetrievalMetrics: (payload: PlanArchiveRetrievalQuery) =>
		planRecordsRequest<PlanArchiveMetricsResponse>('/retrieval/metrics', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	indexArchiveRecords: (payload: PlanArchiveIndexRequest) =>
		planRecordsRequest<PlanArchiveIndexResponse>('/records/index', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	/**
	 * 레코드 상세 조회 (events 포함)
	 */
	get: (id: number) => planRecordsRequest<PlanRecord>(`/records/${id}`),

	getContent: (id: number) =>
		planRecordsRequest<{ id: number; raw_content: string | null }>(`/records/${id}/content`),

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
	 * 레코드 목록 (recurrence_count 필터용, listRecords alias)
	 */
	listRecords: (params?: { skip?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanRecord[]>(`/records${qs ? '?' + qs : ''}`);
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
