/**
 * Dev Runner API - dev-runner 모니터링 및 제어
 */
import { request, API_BASE, getAuthToken, fetchWithTimeout } from './client';

// ============================================================
// Types
// ============================================================

export interface RunRequest {
	plan_file?: string | null;
	max_cycles?: number;
	max_tokens?: number;
	until?: string | null;
	dry_run?: boolean;
	skip_plan?: boolean;
	parallel?: boolean;
	projects?: string | null;
}

export interface RunStatusResponse {
	running: boolean;
	listener_alive: boolean;
	redis_connected: boolean;
	pid: number | null;
	plan_file: string | null;
	start_time: string | null;
	current_cycle: number | null;
	exit_code: number | null;
	crashed: boolean;
	current_plan_name: string | null;
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
	progress: PlanProgressResponse;
	source: string;
	ignored: boolean;
	path_type: 'file' | 'folder' | null;
}

export interface RegisteredPathResponse {
	path: string;
	type: 'file' | 'folder';
	plan_count: number;
}

export interface LogResponse {
	lines: string[];
	total_lines: number;
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
}

export interface DoneResponse {
	success: boolean;
	message: string;
	output: string | null;
	remaining_tasks: number;
	total_tasks: number;
	plan_status: string;
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

// ============================================================
// API prefix (백엔드 라우터: /api/v1/dev-runner)
// ============================================================

const DEV_RUNNER_BASE = '/api/v1/dev-runner';

async function devRunnerRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
	const url = `${DEV_RUNNER_BASE}${endpoint}`;

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
		}),

	stop: () => devRunnerRequest<{ success: boolean }>('/stop', { method: 'POST' }),

	status: () => devRunnerRequest<RunStatusResponse>('/status'),

	resetState: (fullReset: boolean = false) =>
		devRunnerRequest<{ success: boolean; reset_count: number; full_reset: boolean }>(
			`/reset-state?full_reset=${fullReset}`,
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

	hold: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/hold`, { method: 'POST' }),

	unhold: (encodedPath: string) =>
		devRunnerRequest<{ success: boolean }>(`/plans/${encodedPath}/hold`, { method: 'DELETE' })
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

export const devRunnerLogApi = {
	recent: (lines: number = 100) =>
		devRunnerRequest<LogResponse>(`/logs/recent?lines=${lines}`),

	diagnostics: () =>
		devRunnerRequest<{ steps: DiagStep[] }>('/logs/diagnostics'),

	connectStream: (): EventSource => {
		return new EventSource(`${DEV_RUNNER_BASE}/logs/stream`);
	}
};
