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
	file_delete_after: string | null;
	file_removed_at: string | null;
	archive_state?: string | null;
	execution_state?: string | null;
	latest_attempt?: PlanArchiveExecutionAttempt | null;
	next_available_at?: string | null;
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

export interface PlanArchiveSelectedProfile {
	engine: string;
	profile_name: string;
}

export interface PlanArchiveExecutionAttempt {
	id?: number;
	record_id?: number;
	llm_request_id?: number | null;
	engine?: string | null;
	profile_name?: string | null;
	status?: string | null;
	state?: string | null;
	started_at?: string | null;
	completed_at?: string | null;
	requested_at?: string | null;
	error_message?: string | null;
	result?: Record<string, unknown> | null;
	[key: string]: unknown;
}

export interface PlanArchiveExecutionRunPayload {
	record_ids?: number[];
	selected_profiles?: PlanArchiveSelectedProfile[];
}

export interface PlanArchiveExecutionRunResponse {
	queued?: number;
	skipped?: number;
	updated?: number;
	request_ids?: number[];
	attempts?: PlanArchiveExecutionAttempt[];
	records?: PlanRecord[];
	errors?: string[];
	[key: string]: unknown;
}

export interface PlanArchiveExecutionSyncResponse {
	updated?: number;
	records?: PlanRecord[];
	errors?: string[];
	[key: string]: unknown;
}

export interface PlanArchiveExecutionHistoryResponse {
	items: PlanArchiveExecutionAttempt[];
	total?: number;
	limit?: number;
	record_id?: number | null;
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
	retrieval_db_readiness: {
		ok: boolean;
		required_tables: string[];
		missing_tables: string[];
	};
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
	repo_key?: string;
	relation_type?: string;
	semantic_cluster_id?: string;
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
	repo_key?: string;
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
		repo_key?: string | null;
	}>;
	missing_file_candidates: Array<{
		module: string;
		count: number;
		paths: string[];
	}>;
	relation_counts: Record<string, number>;
	chain_depth_max: number;
	repo_counts: Record<string, number>;
	cross_repo_plan_count: number;
	multi_repo_plan_count: number;
	downstream_sync_missing_candidates: Array<{
		repo_key: string;
		path: string;
		count: number;
	}>;
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

export interface PlanArchiveCrossRepoIndexRequest {
	record_id: number;
	max_commits?: number;
	apply?: boolean;
}

export interface PlanArchiveCrossRepoIndexResponse {
	dry_run: boolean;
	record_id: number;
	repos: number;
	indexed: number;
	failed: number;
	skipped: number;
	errors: string[];
}

export interface PlanArchiveAnalyzePayload {
	mode?: 'preview' | 'apply';
	provider?: string | null;
	model?: string | null;
	timeout_seconds?: number;
	include_prompt?: boolean;
	source?: 'auto' | 'raw_content' | 'file_path';
}

export interface PlanArchiveAnalyzeResponse {
	success: boolean;
	mode: string;
	result: Record<string, unknown>;
	raw_response: string;
	provider: string | null;
	model: string | null;
	record_id: number;
	filename_hash: string | null;
	file_path: string | null;
	elapsed_ms: number;
	prompt_preview: string | null;
	prompt_policy_id: string | null;
	prompt_policy_version: string | null;
	warnings: string[];
	error: string | null;
	saved: boolean;
	record_after: Record<string, unknown> | null;
	save_error: string | null;
}

export interface PlanArchiveInsightCandidate {
	title?: string;
	reason?: string;
	evidence_ids?: string[];
}

export interface PlanArchiveInsightReport {
	id: number;
	range_start: string | null;
	range_end: string | null;
	grouping: string;
	metrics_hash: string;
	provider: string;
	model: string;
	status: string;
	review_status: string;
	review_note: string | null;
	promoted_plan_path: string | null;
	warning: string | null;
	error_message: string | null;
	llm_request_id: number | null;
	created_at: string;
	completed_at: string | null;
	summary: string | null;
	root_causes: string[];
	recommendations: string[];
	suggested_plan_candidates: PlanArchiveInsightCandidate[];
}

export interface PlanArchiveInsightReportDetail extends PlanArchiveInsightReport {
	metrics: Record<string, unknown>;
	evidence: Array<Record<string, unknown>>;
	insight: Record<string, unknown>;
	raw_response: string | null;
}

export interface PlanArchiveInsightReportListResponse {
	items: PlanArchiveInsightReport[];
	total: number;
}

export interface PlanArchiveInsightReviewUpdatePayload {
	review_status: 'unreviewed' | 'reviewing' | 'accepted' | 'rejected' | 'promoted';
	review_note?: string | null;
}

export interface PlanArchiveInsightPromotePayload {
	candidate_index: number;
	confirm: boolean;
	title?: string | null;
}

export interface PlanArchiveInsightPromoteResponse {
	path: string;
	report: PlanArchiveInsightReportDetail;
}

export interface PlanArchiveDocPatchProposal {
	id: number;
	plan_record_id: number;
	insight_report_id: number | null;
	status: 'draft' | 'previewed' | 'applied' | 'rejected' | 'failed';
	target_path: string;
	patch_text: string;
	preview_text: string | null;
	changed_lines_summary: Array<Record<string, unknown>>;
	applied_commit: string | null;
	error_message: string | null;
	created_at: string;
	updated_at: string;
	applied_at: string | null;
}

export interface PlanArchiveDocPatchPreviewPayload {
	record_id: number;
	patch_text: string;
	insight_report_id?: number | null;
	target_path?: string | null;
}

export interface PlanArchiveDocPatchApplyPayload {
	confirm: boolean;
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
	queued: boolean;
	request_id: number;
	provider: string;
	model: string;
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

	indexCrossRepoArchive: (payload: PlanArchiveCrossRepoIndexRequest) =>
		planRecordsRequest<PlanArchiveCrossRepoIndexResponse>('/retrieval/cross-repo/index', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	runArchiveExecutions: (payload: PlanArchiveExecutionRunPayload = {}) =>
		planRecordsRequest<PlanArchiveExecutionRunResponse>('/records/archive-executions/run', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	syncArchiveExecutions: () =>
		planRecordsRequest<PlanArchiveExecutionSyncResponse>('/records/archive-executions/sync', {
			method: 'POST'
		}),

	getArchiveExecutionHistory: (params?: { record_id?: number; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.record_id != null) q.set('record_id', String(params.record_id));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanArchiveExecutionHistoryResponse>(`/records/archive-executions/history${qs ? '?' + qs : ''}`);
	},

	analyzeRecord: (recordId: number, payload: PlanArchiveAnalyzePayload = {}) =>
		planRecordsRequest<PlanArchiveAnalyzeResponse>(`/records/${recordId}/analyze`, {
			method: 'POST',
			body: JSON.stringify({ mode: 'preview', ...payload })
		}),

	analyzeDryRun: (recordId: number, payload: Omit<PlanArchiveAnalyzePayload, 'mode'> = {}) =>
		planRecordsRequest<PlanArchiveAnalyzeResponse>(`/records/${recordId}/analyze-dry-run`, {
			method: 'POST',
			body: JSON.stringify({ ...payload, mode: 'preview' })
		}),

	listInsightReports: (params?: {
		status?: string;
		review_status?: string;
		grouping?: string;
		skip?: number;
		limit?: number;
	}) => {
		const q = new URLSearchParams();
		if (params?.status) q.set('status', params.status);
		if (params?.review_status) q.set('review_status', params.review_status);
		if (params?.grouping) q.set('grouping', params.grouping);
		if (params?.skip != null) q.set('skip', String(params.skip));
		if (params?.limit != null) q.set('limit', String(params.limit));
		const qs = q.toString();
		return planRecordsRequest<PlanArchiveInsightReportListResponse>(`/insights/reports${qs ? '?' + qs : ''}`);
	},

	getInsightReport: (id: number) =>
		planRecordsRequest<PlanArchiveInsightReportDetail>(`/insights/reports/${id}`),

	getInsightEvidence: (reportId: number, sourceType: 'record' | 'chunk' | 'file_ref', sourceId: number) =>
		planRecordsRequest<Record<string, unknown>>(`/insights/reports/${reportId}/evidence/${sourceType}/${sourceId}`),

	updateInsightReport: (id: number, payload: PlanArchiveInsightReviewUpdatePayload) =>
		planRecordsRequest<PlanArchiveInsightReportDetail>(`/insights/reports/${id}`, {
			method: 'PATCH',
			body: JSON.stringify(payload)
		}),

	promoteInsightPlan: (id: number, payload: PlanArchiveInsightPromotePayload) =>
		planRecordsRequest<PlanArchiveInsightPromoteResponse>(`/insights/reports/${id}/promote-plan`, {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	previewDocPatch: (payload: PlanArchiveDocPatchPreviewPayload) =>
		planRecordsRequest<PlanArchiveDocPatchProposal>('/doc-patches/preview', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	applyDocPatch: (id: number, payload: PlanArchiveDocPatchApplyPayload) =>
		planRecordsRequest<PlanArchiveDocPatchProposal>(`/doc-patches/${id}/apply`, {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	rejectDocPatch: (id: number) =>
		planRecordsRequest<PlanArchiveDocPatchProposal>(`/doc-patches/${id}/reject`, {
			method: 'POST'
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
	 * archived record를 PlanArchiveExecutionService 기반 LLM 큐에 등록
	 */
	queueArchiveAnalyze: (recordId: number, data: ArchiveAnalyzeRequest) =>
		planRecordsRequest<ArchiveAnalyzeResponse>(`/records/${recordId}/reanalyze`, {
			method: 'POST',
			body: JSON.stringify({ provider: data.provider, model: data.model ?? '', profile_key: data.profile_key ?? null })
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
