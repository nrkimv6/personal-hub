/**
 * Plan Archive schedule and execution API.
 */
import { planRecordsRequest } from './plan-records-request';
import type { PlanRecord } from './plan-records';

export interface PlanArchiveSelectedProfile {
	engine: string;
	profile_name: string;
}

export interface PlanArchiveExecutionTarget {
	provider: string;
	model: string;
	profile_key?: string | null;
	engine?: string | null;
	profile_name?: string | null;
	label?: string | null;
	kind?: 'profile' | 'engine';
}

export interface ArchiveProviderModelProfile {
	provider?: string | null;
	model?: string | null;
	profile_key?: string | null;
	engine?: string | null;
	profile_name?: string | null;
	label?: string | null;
	target_label?: string | null;
}

export interface PlanArchiveExecutionAttempt {
	id?: number;
	record_id?: number;
	llm_request_id?: number | null;
	engine?: string | null;
	profile_name?: string | null;
	requested_target?: ArchiveProviderModelProfile | null;
	effective_target?: ArchiveProviderModelProfile | null;
	actual_target?: ArchiveProviderModelProfile | null;
	effective_provider_model?: ArchiveProviderModelProfile | null;
	actual_provider_model?: ArchiveProviderModelProfile | null;
	assigned_profile?: ArchiveProviderModelProfile | null;
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
	selected_targets?: PlanArchiveExecutionTarget[];
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

// ── Phase 4-A response types ──────────────────────────────────────────────────

export interface ArchiveQueueSummary {
	pending: number;
	processing: number;
	failed: number;
	completed_24h: number;
	recent_failures_by_category: Record<string, number>;
}

export interface ArchiveLLMRequestRow {
	id: number;
	status: string;
	provider: string;
	model: string;
	profile_key?: string | null;
	engine?: string | null;
	profile_name?: string | null;
	target_label?: string | null;
	requested_target?: ArchiveProviderModelProfile | null;
	effective_target?: ArchiveProviderModelProfile | null;
	actual_target?: ArchiveProviderModelProfile | null;
	effective_provider_model?: ArchiveProviderModelProfile | null;
	actual_provider_model?: ArchiveProviderModelProfile | null;
	assigned_profile?: ArchiveProviderModelProfile | null;
	record_id: string | null;
	candidate_key: string | null;
	source_schedule_run_id: number | null;
	failure_category: string | null;
	dedupe_key: string | null;
	requested_at: string | null;
	processed_at: string | null;
	error_message: string | null;
	retry_count: number;
	applied_request_id: number | null;
	is_applied_to_record: boolean;
	save_outcome_status?: string | null;
	save_outcome_reason?: string | null;
}

export interface ArchiveRelatedRecord {
	record_id: number;
	category: string | null;
	tags: string[] | null;
	summary: string | null;
	intent: string | null;
	trigger: string | null;
	scope: string[] | null;
	analyzed_at: string | null;
}

export interface ArchiveAuditSnapshot {
	event_id: number;
	prior_summary: string | null;
	prior_category: string | null;
	prior_tags: string[] | null;
	analyzed_at: string | null;
	created_at: string | null;
}

export interface ArchiveLLMRequestDetail extends ArchiveLLMRequestRow {
	prompt: string | null;
	result: string | null;
	raw_response: string | null;
	cli_options: string | null;
	related_record: ArchiveRelatedRecord | null;
	audit_snapshots: ArchiveAuditSnapshot[];
}

export interface ArchiveLLMRequestListResponse {
	items: ArchiveLLMRequestRow[];
	total: number;
	page: number;
	page_size: number;
	filters: Record<string, unknown>;
}

export interface ArchiveScheduleRunRow {
	id: number;
	schedule_id: number;
	status: string;
	started_at: string | null;
	finished_at: string | null;
	error_message: string | null;
	stop_reason: string | null;
	retry_count: number;
}

export interface ArchiveScheduleRunListResponse {
	items: ArchiveScheduleRunRow[];
	total: number;
	page: number;
	page_size: number;
	filters: Record<string, unknown>;
}

export interface ArchiveExecutionAttemptRow {
	id: number;
	job_id: number;
	llm_request_id: number | null;
	record_id: number | null;
	attempt_index: number;
	status: string;
	provider: string | null;
	model: string | null;
	engine: string | null;
	profile_name: string | null;
	requested_target?: ArchiveProviderModelProfile | null;
	effective_target?: ArchiveProviderModelProfile | null;
	actual_target?: ArchiveProviderModelProfile | null;
	effective_provider_model?: ArchiveProviderModelProfile | null;
	actual_provider_model?: ArchiveProviderModelProfile | null;
	assigned_profile?: ArchiveProviderModelProfile | null;
	error_message: string | null;
	save_outcome_status?: string | null;
	save_outcome_reason?: string | null;
	requested_at: string | null;
	finished_at: string | null;
}

export interface ArchiveExecutionAttemptListResponse {
	items: ArchiveExecutionAttemptRow[];
	total: number;
	page: number;
	page_size: number;
	filters: Record<string, unknown>;
}

export interface ArchiveScheduleDashboardResponse {
	schedule: Record<string, unknown> | null;
	health: Record<string, unknown> | null;
	retrieval_readiness: Record<string, unknown> | null;
	queue_summary: ArchiveQueueSummary;
	recent_requests: ArchiveLLMRequestRow[];
	recent_schedule_runs: ArchiveScheduleRunRow[];
	recent_execution_attempts: ArchiveExecutionAttemptRow[];
}

export interface ArchiveSchedulePauseResumeResponse {
	schedule_id: number;
	enabled: boolean;
	action: string;
}

export interface ArchiveCandidatesQueuePayload {
	candidate_keys?: string[];
	record_ids?: number[];
	selected_targets?: PlanArchiveExecutionTarget[];
}

export interface ArchiveCandidatesQueueResponse {
	queued: number;
	imported: number;
	skipped: number;
	errors: number;
	details?: Array<{ key: string; reason: string }>;
}

export interface ArchiveCandidatePreviewResponse {
	raw_content: string;
	total_bytes: number;
	total_lines: number;
	resolved_path: string;
	filename_hash: string;
}

// ── Phase 4-A/B API wrappers ──────────────────────────────────────────────────

export const archiveScheduleApi = {
	/** archive schedule 운영 대시보드 */
	getDashboard: () =>
		planRecordsRequest<ArchiveScheduleDashboardResponse>('/records/archive-schedule-dashboard'),

	/** LLMRequest 목록 — status/category/record_id/시간 필터, pagination */
	listLLMRequests: (params?: {
		status?: string;
		category?: string;
		record_id?: string;
		source_schedule_run_id?: number;
		since?: string;
		until?: string;
		page?: number;
		page_size?: number;
	}) => {
		const q = new URLSearchParams();
		if (params?.status) q.set('status', params.status);
		if (params?.category) q.set('category', params.category);
		if (params?.record_id) q.set('record_id', params.record_id);
		if (params?.source_schedule_run_id != null) q.set('source_schedule_run_id', String(params.source_schedule_run_id));
		if (params?.since) q.set('since', params.since);
		if (params?.until) q.set('until', params.until);
		if (params?.page != null) q.set('page', String(params.page));
		if (params?.page_size != null) q.set('page_size', String(params.page_size));
		const qs = q.toString();
		return planRecordsRequest<ArchiveLLMRequestListResponse>(`/records/archive-llm-requests${qs ? '?' + qs : ''}`);
	},

	/** LLMRequest 상세 — prompt/result/raw_response/cli_options 포함 */
	getLLMRequestDetail: (requestId: number) =>
		planRecordsRequest<ArchiveLLMRequestDetail>(`/records/archive-llm-requests/${requestId}`),

	/** TaskScheduleRun history pagination */
	listScheduleRuns: (params?: {
		status?: string;
		since?: string;
		until?: string;
		page?: number;
		page_size?: number;
	}) => {
		const q = new URLSearchParams();
		if (params?.status) q.set('status', params.status);
		if (params?.since) q.set('since', params.since);
		if (params?.until) q.set('until', params.until);
		if (params?.page != null) q.set('page', String(params.page));
		if (params?.page_size != null) q.set('page_size', String(params.page_size));
		const qs = q.toString();
		return planRecordsRequest<ArchiveScheduleRunListResponse>(`/records/archive-schedule-runs${qs ? '?' + qs : ''}`);
	},

	/** PlanArchiveExecutionAttempt history pagination */
	listExecutionAttempts: (params?: {
		status?: string;
		record_id?: number;
		since?: string;
		until?: string;
		page?: number;
		page_size?: number;
	}) => {
		const q = new URLSearchParams();
		if (params?.status) q.set('status', params.status);
		if (params?.record_id != null) q.set('record_id', String(params.record_id));
		if (params?.since) q.set('since', params.since);
		if (params?.until) q.set('until', params.until);
		if (params?.page != null) q.set('page', String(params.page));
		if (params?.page_size != null) q.set('page_size', String(params.page_size));
		const qs = q.toString();
		return planRecordsRequest<ArchiveExecutionAttemptListResponse>(`/records/archive-execution-attempts${qs ? '?' + qs : ''}`);
	},

	/** admin: archive backlog 실행 */
	runArchiveExecutions: (payload: PlanArchiveExecutionRunPayload = {}) =>
		planRecordsRequest<PlanArchiveExecutionRunResponse>('/records/archive-executions/run', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	/** admin: archive execution 상태 동기화 */
	syncArchiveExecutions: () =>
		planRecordsRequest<PlanArchiveExecutionSyncResponse>('/records/archive-executions/sync', {
			method: 'POST'
		}),

	/** admin: schedule 일시정지 */
	pause: () =>
		planRecordsRequest<ArchiveSchedulePauseResumeResponse>('/records/archive-schedule/pause', { method: 'POST' }),

	/** admin: schedule 재개 */
	resume: () =>
		planRecordsRequest<ArchiveSchedulePauseResumeResponse>('/records/archive-schedule/resume', { method: 'POST' }),

	/** admin: candidate 일괄 큐잉 */
	queueCandidates: (payload: ArchiveCandidatesQueuePayload) =>
		planRecordsRequest<ArchiveCandidatesQueueResponse>('/records/archive-candidates/queue', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),

	/** candidate 미리보기 (file_only row 확인용) */
	previewCandidate: (candidateKey: string) => {
		const q = new URLSearchParams({ candidate_key: candidateKey });
		return planRecordsRequest<ArchiveCandidatePreviewResponse>(`/records/archive-candidates/preview?${q}`);
	},
};
