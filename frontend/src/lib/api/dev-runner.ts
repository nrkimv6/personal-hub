/**
 * Dev Runner API - dev-runner 모니터링 및 제어
 */
import { request, API_BASE, getAuthToken, fetchWithTimeout } from './client';

// ============================================================
// Types
// ============================================================

export interface RunRequest {
	plan_file?: string | null;
	engine?: string;
	fix_engine?: string;
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
	trigger?: string | null;
	visible: boolean;
	orphan: boolean;
	exit_reason?: string | null;
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
}

export interface RegisteredPathResponse {
	path: string;
	type: 'file' | 'folder';
	plan_count: number;
	path_type: string; // "plan" | "archive"
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
		const message = typeof detail === 'string' ? detail : detail?.message || '요청 실패';
		throw new Error(message);
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

export interface AllEnginesConfig {
	[engine: string]: EngineConfig;
}

export const devRunnerEngineApi = {
	list: () => devRunnerRequest<AllEnginesConfig>('/engines'),
	// 예: { models: { "auto-verify": "gpt-5.3-codex" } } 처럼 phase key 일부만 PATCH 가능
	update: (engine: string, config: Partial<EngineConfig>) =>
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

	runners: () => devRunnerRequest<RunnerListItem[]>('/runners'),

	resetState: (fullReset: boolean = false) =>
		devRunnerRequest<{ success: boolean; reset_count: number; full_reset: boolean }>(
			`/reset-state?full_reset=${fullReset}`,
			{ method: 'POST' }
		),

	retryMerge: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string; conflict?: boolean }>(
			`/runners/${runnerId}/retry-merge`,
			{ method: 'POST' }
		),

	resolveConflict: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string }>(
			`/runners/${runnerId}/resolve-conflict`,
			{ method: 'POST' }
		),

	cleanupWorktree: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string }>(
			`/runners/${runnerId}/worktree`,
			{ method: 'DELETE' }
		),

	directMerge: (branch: string, worktreePath?: string, planFile?: string) =>
		devRunnerRequest<{ success: boolean; message: string; runner_id?: string }>(
			'/merge/direct',
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ branch, worktree_path: worktreePath ?? null, plan_file: planFile ?? null }),
			}
		),

	stopAll: () => devRunnerRequest<{ stopped: number }>('/stop-all', { method: 'POST' }),

	dismissTab: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; runner_id: string }>(
			`/runners/${runnerId}/tab`,
			{ method: 'DELETE' }
		),

	kill: (runnerId: string) =>
		devRunnerRequest<{ success: boolean; message: string }>(
			`/runners/${runnerId}/kill`,
			{ method: 'POST' }
		),

	cleanupStale: () =>
		devRunnerRequest<{ success: boolean; cleaned: number; detail: { cleaned_active: number; cleaned_recent: number } }>(
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

	addPath: (path: string) =>
		devRunnerRequest<{ success: boolean; path: string; type: 'file' | 'folder' }>('/plans/paths', {
			method: 'POST',
			body: JSON.stringify({ path })
		}),

	removePath: (path: string) =>
		devRunnerRequest<{ success: boolean }>('/plans/paths', {
			method: 'DELETE',
			body: JSON.stringify({ path })
		}),

	listPaths: () =>
		devRunnerRequest<RegisteredPathResponse[]>('/plans/paths'),

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
		devRunnerRequest<{ request_id: number }>(`/plans/${encodedPath}/summary`, { method: 'POST' })
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
		return new EventSource(`${DEV_RUNNER_BASE}/logs/stream?runner_id=${runnerId}&since_line=${sinceLine}`);
	},

	connectMergeStream: (runnerId: string): EventSource => {
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

	retry: (runnerId: string): Promise<unknown> =>
		devRunnerRequest(`/merge/${runnerId}/retry`, { method: 'POST' }),

	revert: (runnerId: string): Promise<unknown> =>
		devRunnerRequest(`/merge/${runnerId}/revert`, { method: 'POST' }),
};


export interface DevRunnerSettings {
	max_concurrent_runners: number;
	updated_at: string | null;
}

export const devRunnerSettingsApi = {
	get: (): Promise<DevRunnerSettings> =>
		devRunnerRequest<DevRunnerSettings>('/settings'),

	update: (maxRunners: number): Promise<DevRunnerSettings> =>
		devRunnerRequest<DevRunnerSettings>('/settings', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ max_concurrent_runners: maxRunners }),
		}),
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
