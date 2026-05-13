/**
 * Dev Runner API - dev-runner 모니터링 및 제어
 */
import { apiGate } from '$lib/stores/apiGate.svelte';
import { request, API_BASE, getAuthToken, fetchWithTimeout, ApiGateClosedError } from './client';

// ============================================================
// ApiError — HTTP 에러 detail 객체를 보존하는 커스텀 에러
// ============================================================

export class ApiError extends Error {
	status: number;
	detail?: Record<string, unknown>;
	constructor(message: string, status: number, detail?: Record<string, unknown>) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

// ============================================================
// Types
// ============================================================

export interface RunRequest {
	plan_file?: string | null;
	engine?: string;
	fix_engine?: string;
	profile?: string | null;
	max_cycles?: number;
	max_tokens?: number;
	until?: string | null;
	dry_run?: boolean;
	skip_plan?: boolean;
	parallel?: boolean;
	projects?: string | null;
	worktree?: boolean;
	trigger?: string | null;
}

export interface RunStatusResponse {
	running: boolean;
	engine?: string;
	listener_alive: boolean;
	redis_connected: boolean;
	pid: number | null;
	plan_file: string | null;
	start_time: string | null;
	current_cycle: number | null;
	exit_code: number | null;
	crashed: boolean;
	current_plan_name: string | null;
	runner_id: string | null;
	execution_count?: number | null;
	attached?: boolean;
	worktree_exists?: boolean | 'unknown';
	branch_exists?: boolean | 'unknown';
	branch_merged_to_main?: boolean | 'unknown';
	metadata_checked_at?: string;
	exit_reason?: string | null;
	error?: string | null;
	display_state?: string;
	display_label?: string;
	display_severity?: 'info' | 'warn' | 'error' | 'approval' | 'success' | 'muted';
	display_secondary?: string | null;
	hide_stale_branch_badge?: boolean;
	claim_id?: string | null;
	claim_state?: string | null;
	claim_owner_runner_id?: string | null;
	claim_message?: string | null;
	gate_evidence_summary?: Record<string, unknown> | null;
}

export interface RunnerListItem {
	runner_id: string;
	running: boolean;
	plan_file: string | null;
	engine: string | null;
	start_time: string | null;
	pid: number | null;
	worktree_path: string | null;
	branch: string | null;
	merge_status: string | null;
	merge_reason?: string | null;
	merge_message?: string | null;
	trigger?: string | null;
	visible: boolean;
	orphan: boolean;
	orphan_alive?: boolean;
	redis_missing?: boolean;
	log_file_found?: boolean;
	exit_reason?: string | null;
	error?: string | null;
	execution_count?: number | null;
	display_plan_name?: string | null;
	remaining_post_merge_tasks?: number | null;
	merge_evidence_missing?: boolean | null;
	worktree_exists?: boolean | 'unknown';
	branch_exists?: boolean | 'unknown';
	branch_merged_to_main?: boolean | 'unknown';
	metadata_checked_at?: string;
	display_state?: string;
	display_label?: string;
	display_severity?: 'info' | 'warn' | 'error' | 'approval' | 'success' | 'muted';
	display_secondary?: string | null;
	hide_stale_branch_badge?: boolean;
	gate_evidence_summary?: Record<string, unknown> | null;
}

export interface OrphanRunnerCandidate {
	runner_id: string;
	plan_file: string | null;
	engine: string | null;
	trigger: string | null;
	pid: number | null;
	pid_kind: 'parent' | 'child_engine' | 'none';
	log_file: string | null;
	log_mtime: string | null;
	start_time: string | null;
	execution_count: number | null;
	worktree_path: string | null;
	branch: string | null;
	confidence: 'high' | 'medium' | 'low';
	reattach_mode: 'full' | 'log_only_child' | 'log_only';
	can_reattach: boolean;
	can_force_kill: boolean;
	warnings: string[];
}

export interface ReattachRunnerResponse {
	success: boolean;
	runner_id: string;
	message: string;
	candidate: OrphanRunnerCandidate;
	reattach_mode: 'full' | 'log_only_child' | 'log_only';
}

export interface PlanProgressResponse {
	done: number;
	total: number;
	percent: number;
}

export interface PlanFileResponse {
	path: string;
	filename: string;
	status: string;
	progress: PlanProgressResponse | null;  // 리스트 API에서는 null, 상세 조회 시 포함
	source: string;
	ignored: boolean;
	path_type: 'file' | 'folder' | null;
	summary?: string | null;  // > 요약: 헤더에서 추출한 요약 텍스트
	branch?: string | null;  // > branch: 헤더에서 추출한 impl 브랜치명
	worktree_path?: string | null;  // > worktree: 헤더에서 추출한 워크트리 경로
	worktree_owner?: string | null;  // > worktree-owner: 헤더에서 추출한 소유 plan 경로
	execution_claim_id?: string | null;
	execution_claim_state?: string | null;  // queued | active | released | stale
	execution_claim_runner_id?: string | null;
	execution_claim_stale?: boolean;
}

export interface RegisteredPathResponse {
	path: string;
	type: 'file' | 'folder';
	plan_count: number;
	path_type: string; // "plan" | "archive"
}

export interface PlanStorageRootChangeItem {
	status: string;
	path: string;
}

export interface PlanStorageRootStatusItem {
	project: string;
	repo_root: string;
	worktree_path: string;
	branch: string | null;
	upstream: string | null;
	exists: boolean;
	status: 'clean' | 'dirty' | 'sync_needed' | 'missing' | 'unknown' | string;
	dirty_count: number;
	docs_changes_count: number;
	archive_changes_count: number;
	policy_changes_count: number;
	ahead: number;
	behind: number;
	push_needed: boolean;
	checked_at: string;
	representative_changes: PlanStorageRootChangeItem[];
	error: string | null;
}

export interface PlanStorageRootStatusResponse {
	checked_at: string;
	roots: PlanStorageRootStatusItem[];
	total: number;
	dirty_count: number;
	push_needed_count: number;
}

export interface LogResponse {
	lines: string[];
	total_lines: number;
	from_line: number;
}

export interface CurrentTrackingResponse {
	text: string;
	confidence: 'HIGH' | 'MEDIUM' | string;
	line_num: number | null;
	plan_file: string | null;
	stale: boolean;
}

export interface PlanItemResponse {
	level: number;
	text: string;
	checked: boolean;
	children: PlanItemResponse[];
	file_path: string | null;
}

export interface PlanPhaseResponse {
	name: string;
	items: PlanItemResponse[];
	done_count: number;
	total_count: number;
}

export interface PlanDetailResponse {
	path: string;
	filename: string;
	status: string;
	phases: PlanPhaseResponse[];
	progress: PlanProgressResponse;
	summary?: string | null;
}

export interface DoneResponse {
	success: boolean;
	message: string;
	output: string | null;
	remaining_tasks: number;
	total_tasks: number;
	plan_status: string;
	plans?: PlanFileResponse[];
}

export interface BatchDoneResultItem {
	path: string;
	filename: string;
	success: boolean;
	message: string;
}

export interface BatchDoneResponse {
	total: number;
	success: number;
	failed: number;
	results: BatchDoneResultItem[];
}

export interface VerifyResult {
	total: number;
	verified: number;
	unverified_items: string[];
	percent: number;
	can_done: boolean;
}

export interface AddProjectResponse {
	added: string[];
	skipped: string[];
}

// ============================================================
// API prefix (백엔드 라우터: /api/v1/dev-runner)
// ============================================================

const DEV_RUNNER_BASE = '/api/v1/dev-runner';

async function devRunnerRequest<T>(endpoint: string, options: RequestInit = {}, timeout?: number): Promise<T> {
	const url = `${DEV_RUNNER_BASE}${endpoint}`;

	// dev-runner uses fetchWithTimeout directly, so apply the same gate policy here.
	await apiGate.ensureInitialStatus();
	if (apiGate.state !== 'open') {
		throw new ApiGateClosedError();
	}

	const token = getAuthToken();
	const headers: HeadersInit = {
		'Content-Type': 'application/json',
		...(token ? { Authorization: `Bearer ${token}` } : {}),
		...options.headers
	};

	const response = await fetchWithTimeout(url, { ...options, headers, credentials: 'include' }, timeout);

	if (!response.ok) {
		const error = await response.json().catch(() => ({ detail: response.statusText }));
		const detail = error.detail;
		const message = typeof detail === 'string' ? detail : (detail?.message || '요청 실패');
		const err = new ApiError(message, response.status, typeof detail === 'object' ? detail : undefined);
		throw err;
	}

	if (response.status === 204) {
		return null as T;
	}

	return response.json();
}

// ============================================================
// Engines API
// ============================================================

export interface EngineConfig {
	default_model: string;
	flags: string[];
	models: Record<string, string>;
}

export interface EngineConfigUpdatePayload extends Partial<EngineConfig> {
	overwrite_all_phases?: boolean;
}

export interface AllEnginesConfig {
	[engine: string]: EngineConfig;
}

export const devRunnerEngineApi = {
	list: () => devRunnerRequest<AllEnginesConfig>('/engines'),
	// 예: { models: { "auto-verify": "gpt-5.3-codex" } } 처럼 phase key 일부만 PATCH 가능
	update: (engine: string, config: EngineConfigUpdatePayload) =>
		devRunnerRequest<{ success: boolean; message: string }>(`/engines/${engine}`, {
			method: 'PUT',
			body: JSON.stringify(config)
		})
};

// ============================================================
// Tasks API
// ============================================================

export const devRunnerTaskApi = {
	currentTracking: () =>
		devRunnerRequest<CurrentTrackingResponse | null>('/tasks/current-tracking'),
};

export interface DevRunnerCommandAccepted {
	success: boolean;
	status: 'accepted';
	command_id: string;
	result_key?: string;
	message: string;
}

export interface DevRunnerCommandResult {
	success: boolean;
	status: 'pending' | 'completed' | 'failed';
	command_id: string;
	message: string;
	result?: Record<string, unknown>;
}

// ============================================================
// Runner API
// ============================================================

export const devRunnerRunnerApi = {
	start: (data: RunRequest) =>
		devRunnerRequest<RunStatusResponse>('/run', {
			method: 'POST',
			body: JSON.stringify(data)
		}, 60000),

	stop: (runnerId: string) =>
		devRunnerRequest<{ message: string }>(`/runners/${runnerId}/stop`, { method: 'POST' }),

	stopLegacy: () => devRunnerRequest<{ message: string }>('/stop', { method: 'POST' }),

	status: () => devRunnerRequest<RunStatusResponse>('/status'),

	commandResult: (commandId: string) =>
		devRunnerRequest<DevRunnerCommandResult>(`/commands/${commandId}`),

	runners: () => devRunnerRequest<RunnerListItem[]>('/runners'),

	discoverOrphanRunners: () => devRunnerRequest<OrphanRunnerCandidate[]>('/runners/orphans'),

	reattachRunner: (runnerId: string, payload?: { force?: boolean; expected_plan_file?: string | null; expected_log_file?: string | null }) =>
		devRunnerRequest<ReattachRunnerResponse>(
			`/runners/${runnerId}/reattach`,
			{
				method: 'POST',
				body: JSON.stringify(payload ?? {})
			}
		),

	killOrphanRunner: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string; pid?: number }>(
			`/runners/${runnerId}/orphans/kill`,
			{ method: 'POST' }
		),

	resetState: (fullReset: boolean = false) =>
		devRunnerRequest<{ success: boolean; reset_count: number; full_reset: boolean }>(
			`/reset-state?full_reset=${fullReset}`,
			{ method: 'POST' }
		),

	retryMerge: (
		runnerId: string,
		payload?: { worktree_path?: string | null; plan_file?: string | null; branch?: string | null; approve_service_lock?: boolean }
	) =>
		devRunnerRequest<DevRunnerCommandAccepted>(
			`/runners/${runnerId}/retry-merge`,
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload ?? {}),
			}
		),

	resolveConflict: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string }>(
			`/runners/${runnerId}/resolve-conflict`,
			{ method: 'POST' }
		),

	cleanupWorktree: (runnerId: string) =>
		devRunnerRequest<DevRunnerCommandAccepted>(
			`/runners/${runnerId}/worktree`,
			{ method: 'DELETE' }
		),

	directMerge: (branch: string, worktreePath?: string, planFile?: string, approveServiceLock?: boolean) =>
		devRunnerRequest<DevRunnerCommandAccepted>(
			'/merge/direct',
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					branch,
					worktree_path: worktreePath ?? null,
					plan_file: planFile ?? null,
					approve_service_lock: Boolean(approveServiceLock),
				}),
			}
		),

	stopAll: () => devRunnerRequest<{ stopped: number }>('/stop-all', { method: 'POST' }),

	restartListener: () => devRunnerRequest<{ success: boolean; message: string }>('/restart-listener', { method: 'POST' }),

	dismissTab: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; runner_id: string }>(
			`/runners/${runnerId}/tab`,
			{ method: 'DELETE' }
		),

	kill: (runnerId: string) =>
		devRunnerRequest<DevRunnerCommandAccepted>(
			`/runners/${runnerId}/kill`,
			{ method: 'POST' }
		),

	cleanupStale: () =>
		devRunnerRequest<{
			success: boolean;
			cleaned: number;
			cleaned_active: number;
			cleaned_recent: number;
			preserved_recent?: number;
			detail: {
				cleaned_active: number;
				cleaned_recent: number;
				preserved_recent?: number;
			};
		}>(
			'/runners/cleanup-stale',
			{ method: 'POST' }
		)
};

// ============================================================
// Plans API
// ============================================================

export const devRunnerPlanApi = {
	list: () => devRunnerRequest<PlanFileResponse[]>('/plans'),

	ignored: () => devRunnerRequest<PlanFileResponse[]>('/plans/ignored'),

	get: (encodedPath: string) =>
		devRunnerRequest<PlanProgressResponse>(`/plans/${encodedPath}`),

	sync: () => devRunnerRequest<{ synced: number; added: number; removed: number; updated: number }>('/plans/sync', { method: 'POST' }),

	addPath: (path: string, pathType: 'plan' | 'archive' = 'plan') =>
		devRunnerRequest<{ success: boolean; path: string; type: 'file' | 'folder' }>('/plans/paths', {
			method: 'POST',
			body: JSON.stringify({ path, path_type: pathType })
		}),

	removePath: (path: string) =>
		devRunnerRequest<{ success: boolean }>('/plans/paths', {
			method: 'DELETE',
			body: JSON.stringify({ path })
		}),

	listPaths: () =>
		devRunnerRequest<RegisteredPathResponse[]>('/plans/paths'),

	storageRootsStatus: () =>
		devRunnerRequest<PlanStorageRootStatusResponse>('/plans/storage-roots/status'),

	items: (encodedPath: string) =>
		devRunnerRequest<PlanDetailResponse>(`/plans/${encodedPath}/items`),

	ignore: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/ignore`, { method: 'POST' }),

	unignore: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/ignore`, { method: 'DELETE' }),

	done: (encodedPath: string) =>
		devRunnerRequest<DoneResponse>(`/plans/${encodedPath}/done`, { method: 'POST' }),

	batchDone: () =>
		devRunnerRequest<BatchDoneResponse>('/plans/batch-done', { method: 'POST' }),

	verify: (encodedPath: string) =>
		devRunnerRequest<VerifyResult>(`/plans/${encodedPath}/verify`),

	batchVerifyDone: () =>
		devRunnerRequest<BatchDoneResponse>('/plans/batch-verify-done', { method: 'POST' }),

	hold: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/hold`, { method: 'POST' }),

	unhold: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/hold`, { method: 'DELETE' }),

	content: (encodedPath: string) =>
		devRunnerRequest<{ content: string; path: string }>(`/plans/${encodedPath}/content`),

	addProject: (path: string) =>
		devRunnerRequest<AddProjectResponse>('/plans/paths/project', {
			method: 'POST',
			body: JSON.stringify({ path })
		}),

	patchStatus: (encodedPath: string, status: string) =>
		devRunnerRequest<{ path: string; status: string }>(`/plans/${encodedPath}/status`, {
			method: 'PATCH',
			body: JSON.stringify({ status })
		}),

	generateSummary: (encodedPath: string) =>
		devRunnerRequest<{ request_id: number }>(`/plans/${encodedPath}/summary`, { method: 'POST' }),

	releaseClaim: (encodedPath: string) =>
		devRunnerRequest<{ ok: boolean; claim_id: string }>(`/plans/${encodedPath}/claim`, { method: 'DELETE' })
};

// ============================================================
// Logs API
// ============================================================

export interface DiagStep {
	step: number;
	name: string;
	ok: boolean;
	detail: string;
}

// ── Run History types ──

export interface RunHistoryItem {
	runner_id: string;
	plan_file: string | null;
	engine: string | null;
	status: 'running' | 'completed' | 'unknown';
	pid: number | null;
	start_time: string | null;
	end_time: string | null;
	log_file: string | null;
	has_log: boolean;
	worktree_path: string | null;
	branch: string | null;
	merge_status: string | null;
	trigger?: string | null;
	execution_count?: number | null;
}

export interface RunHistoryResponse {
	runs: RunHistoryItem[];
	total: number;
}

export interface FullLogResponse {
	lines: string[];
	total_lines: number;
	offset: number;
	has_more: boolean;
}

export const devRunnerLogApi = {
	recent: (runnerId: string, lines: number = 100) =>
		devRunnerRequest<LogResponse>(`/logs/recent?runner_id=${runnerId}&lines=${lines}`),

	diagnostics: () =>
		devRunnerRequest<{ steps: DiagStep[] }>('/logs/diagnostics'),

	connectStream: (runnerId: string, sinceLine: number = 0): EventSource => {
		if (apiGate.state !== 'open') {
			throw new ApiGateClosedError();
		}
		return new EventSource(`${DEV_RUNNER_BASE}/logs/stream?runner_id=${runnerId}&since_line=${sinceLine}`);
	},

	connectMergeStream: (runnerId: string): EventSource => {
		if (apiGate.state !== 'open') {
			throw new ApiGateClosedError();
		}
		return new EventSource(`${DEV_RUNNER_BASE}/merge-log/stream?runner_id=${runnerId}`);
	},

	history: (limit: number = 20, offset: number = 0, visibleOnly: boolean = false) =>
		devRunnerRequest<RunHistoryResponse>(`/logs/history?limit=${limit}&offset=${offset}${visibleOnly ? '&visible_only=true' : ''}`),

	full: (runnerId: string, offset: number = 0, limit: number = 500) =>
		devRunnerRequest<FullLogResponse>(`/logs/full?runner_id=${runnerId}&offset=${offset}&limit=${limit}`),

	system: (lines: number = 200) =>
		devRunnerRequest<LogResponse>(`/logs/system?lines=${lines}`),
};

// ============================================================
// Events API (SSE — Redis keyspace notifications 기반)
// ============================================================

import { createFetchSSE } from '$lib/utils/sse-fetch';

export interface EventsSSEOptions {
	onEvent?: (eventName: string, data: string) => void;
	onOpen?: () => void;
	onError?: (err: unknown) => void;
}

export const devRunnerEventApi = {
	/** Redis keyspace notifications 기반 실시간 SSE 스트림에 연결 */
	connectEvents: (options: EventsSSEOptions = {}): { close: () => void } => {
		return createFetchSSE({
			url: `${DEV_RUNNER_BASE}/events`,
			...options
		});
	}
};

// ============================================================
// Merge Queue Types & API
// ============================================================

export interface MergeQueueItem {
	queue_key?: string;
	runner_id: string;
	branch: string;
	plan_file: string;
	project: string;
	status: string;
	timestamp: string;
	worktree_path: string;
}

export interface MergeStatusResponse {
	runner_id: string;
	status: string;
	test_passed: boolean | null;
	fix_attempts: number;
	message: string;
	reason?: string | null;
	quarantine_diff_path?: string | null;
}

export interface MergeHistoryItem {
	runner_id: string;
	branch: string;
	plan_file: string;
	project: string;
	timestamp: string;
	worktree_path: string;
	status: string;
	success: boolean;
	test_passed: boolean | null;
	fix_attempts: number;
	message: string;
	reason?: string | null;
	quarantine_diff_path?: string | null;
}

export const devRunnerMergeApi = {
	queue: (): Promise<MergeQueueItem[]> =>
		devRunnerRequest<MergeQueueItem[]>('/merge-queue'),

	queueLength: (): Promise<{ length: number }> =>
		devRunnerRequest<{ length: number }>('/merge-queue-length'),

	history: (limit?: number): Promise<MergeHistoryItem[]> =>
		devRunnerRequest<MergeHistoryItem[]>(`/merge-history${limit ? `?limit=${limit}` : ''}`),

	status: (runnerId: string): Promise<MergeStatusResponse> =>
		devRunnerRequest<MergeStatusResponse>(`/merge/${runnerId}`),

	retry: (
		runnerId: string,
		payload?: { worktree_path?: string | null; plan_file?: string | null; branch?: string | null; approve_service_lock?: boolean }
	): Promise<unknown> =>
		devRunnerRequest(`/merge/${runnerId}/retry`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload ?? {}),
		}),

	revert: (runnerId: string): Promise<unknown> =>
		devRunnerRequest(`/merge/${runnerId}/revert`, { method: 'POST' }),
};


export interface DevRunnerSettings {
	max_concurrent_runners: number;
	default_engine: string;
	default_fix_engine: string;
	updated_at: string | null;
}

export interface DevRunnerSettingsUpdatePayload {
	max_concurrent_runners?: number;
	default_engine?: string;
	default_fix_engine?: string;
}

export const devRunnerSettingsApi = {
	get: (): Promise<DevRunnerSettings> =>
		devRunnerRequest<DevRunnerSettings>('/settings'),

	update: (payload: number | DevRunnerSettingsUpdatePayload): Promise<DevRunnerSettings> => {
		const body =
			typeof payload === 'number'
				? { max_concurrent_runners: payload }
				: payload;
		return devRunnerRequest<DevRunnerSettings>('/settings', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});
	},
};


export interface WorkflowResponse {
	id: number;
	slug: string;
	plan_file: string | null;
	branch: string | null;
	runner_id: string | null;
	status: string;
	engine: string | null;
	error_message: string | null;
	commit_hash: string | null;
	worktree_path: string | null;
	created_at: string | null;
	started_at: string | null;
	merged_at: string | null;
	finished_at: string | null;
}

export interface WorkflowCreateRequest {
	plan_file?: string;
	slug?: string;
}

export interface CommitDiffStat {
	file: string;
	changes: string;
}

export interface WorktreeCommit {
	hash: string;
	short_hash: string;
	message: string;
	date: string;
	diff_stat: CommitDiffStat[];
}

export interface WorktreeInfoLite {
	branch: string;
	worktree_path: string;
	created_at: string | null;
	ahead: number;
	behind: number;
	locked: boolean;
	commit_count: number;
	plan_file: string | null;
	plan_mtime: string | null;
	is_test: boolean;
	plan_file_archived: boolean;
	cleanable: boolean;
}

export interface WorktreeInfoFull extends WorktreeInfoLite {
	commits: WorktreeCommit[];
}

export interface MainDirtyStatus {
	dirty_count: number;
	files: string[];
}

export interface PlanOnlyBranch {
	plan_file: string;
	branch: string;
	plan_mtime: string | null;
	is_test: boolean;
}

export interface BranchUnresolvedPlan {
	plan_file: string;
	reason: string;
	plan_mtime: string | null;
	is_test: boolean;
}

export interface WorktreeCleanupRequest {
	branches: string[];
	dry_run?: boolean;
}

export interface WorktreeCleanupResult {
	branch: string;
	status: 'removed' | 'skipped' | 'failed';
	reason: string;
	worktree_removed: boolean;
	branch_removed: boolean;
}

export interface WorktreeCleanupResponse {
	results: WorktreeCleanupResult[];
	summary: Record<string, number>;
}

export interface WorktreeListResponse {
	worktrees: WorktreeInfoLite[];
	plan_only: PlanOnlyBranch[];
	branch_unresolved: BranchUnresolvedPlan[];
	main_dirty: MainDirtyStatus;
}

export interface RepoOption {
	id: number;
	alias: string;
	path: string;
}

export const devRunnerWorktreeApi = {
	list: (repoId?: number): Promise<WorktreeInfoFull[]> => {
		const query = repoId !== undefined ? `?repo_id=${repoId}` : '';
		return devRunnerRequest<WorktreeInfoFull[]>(`/worktrees${query}`);
	},
	listV2: (repoId?: number): Promise<WorktreeListResponse> => {
		const query = repoId !== undefined ? `?repo_id=${repoId}` : '';
		return devRunnerRequest<WorktreeListResponse>(`/worktrees/v2${query}`);
	},
	listCommits: (branch: string, repoId?: number): Promise<WorktreeCommit[]> => {
		const query = new URLSearchParams({ branch });
		if (repoId !== undefined) {
			query.set('repo_id', String(repoId));
		}
		return devRunnerRequest<WorktreeCommit[]>(`/worktrees/v2/commits?${query.toString()}`);
	},
	listRepos: (): Promise<RepoOption[]> => devRunnerRequest<RepoOption[]>('/worktrees/repos'),
	cleanup: (
		req: WorktreeCleanupRequest,
		repoId?: number,
		timeoutMs?: number,
	): Promise<WorktreeCleanupResponse> => {
		const query = repoId !== undefined ? `?repo_id=${repoId}` : '';
		return devRunnerRequest<WorktreeCleanupResponse>(`/worktrees/cleanup${query}`, {
			method: 'POST',
			body: JSON.stringify(req),
		}, timeoutMs);
	},
};

export const devRunnerWorkflowApi = {
	list: (params?: { status?: string; limit?: number; offset?: number }): Promise<WorkflowResponse[]> => {
		const qs = new URLSearchParams();
		if (params?.status) qs.set('status', params.status);
		if (params?.limit !== undefined) qs.set('limit', String(params.limit));
		if (params?.offset !== undefined) qs.set('offset', String(params.offset));
		const query = qs.toString() ? `?${qs.toString()}` : '';
		return devRunnerRequest<WorkflowResponse[]>(`/workflows${query}`);
	},

	get: (id: number): Promise<WorkflowResponse> =>
		devRunnerRequest<WorkflowResponse>(`/workflows/${id}`),

	create: (req: WorkflowCreateRequest): Promise<WorkflowResponse> =>
		devRunnerRequest<WorkflowResponse>('/workflows', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(req),
		}),

	cancel: (id: number): Promise<WorkflowResponse> =>
		devRunnerRequest<WorkflowResponse>(`/workflows/${id}/cancel`, { method: 'PATCH' }),

	reset: (id: number, cleanupWorktree?: boolean): Promise<WorkflowResponse> =>
		devRunnerRequest<WorkflowResponse>(`/workflows/${id}/reset${cleanupWorktree ? '?cleanup_worktree=true' : ''}`, { method: 'PATCH' }),

	resetAllOrphans: (): Promise<{ reset_count: number }> =>
		devRunnerRequest<{ reset_count: number }>('/workflows/reset-all-orphans', { method: 'POST' }),
};

// ─── Daily Reports ─────────────────────────────────────────────────────────

export interface DailyReportSummary {
	date: string;
	generated_at?: string;
	summary: { total: number; completed: number; failed: number; skipped: number };
	html_available: boolean;
}

export interface DailyReportRun {
	plan_id: string;
	scope: string;
	status: string;
	merged: boolean;
	changed_files: string[];
	tc_results: Record<string, unknown>;
	suspicions: string[];
	log_path: string;
	started_at: string;
	ended_at: string;
}

export interface DailyReport {
	date: string;
	generated_at: string;
	summary: DailyReportSummary['summary'];
	runs: DailyReportRun[];
}

export const dailyReportApi = {
	list: (): Promise<DailyReportSummary[]> =>
		devRunnerRequest<DailyReportSummary[]>('/daily-reports'),

	get: (reportDate: string): Promise<DailyReport> =>
		devRunnerRequest<DailyReport>(`/daily-reports/${reportDate}`),
};
