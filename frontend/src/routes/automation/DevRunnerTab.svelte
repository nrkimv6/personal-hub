<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import TaskList from '$lib/components/dev-runner/TaskList.svelte';
	import RunControl from '$lib/components/dev-runner/RunControl.svelte';
	import PlanList from '$lib/components/dev-runner/PlanList.svelte';
	import PlanMarkdownPreview from '$lib/components/dev-runner/PlanMarkdownPreview.svelte';
	import RunnerInstanceTab from '$lib/components/dev-runner/RunnerInstanceTab.svelte';
	import CurrentTrackingCard from '$lib/components/dev-runner/CurrentTrackingCard.svelte';
	import MergeQueuePanel from '$lib/components/dev-runner/MergeQueuePanel.svelte';
	import UnifiedLogsView from '$lib/components/dev-runner/UnifiedLogsView.svelte';
	import LogHistoryPanel from '$lib/components/dev-runner/LogHistoryPanel.svelte';
	import DevRunnerSettingsPanel from '$lib/components/dev-runner/DevRunnerSettingsPanel.svelte';
	import WorkflowList from '$lib/components/dev-runner/WorkflowList.svelte';
	import RunStatusBar from '$lib/components/dev-runner/RunStatusBar.svelte';
	import {
		devRunnerTaskApi,
		devRunnerRunnerApi,
		devRunnerEventApi
	} from '$lib/api';
	import { devRunnerPlanApi } from '$lib/api/dev-runner';
	import { encodePathToBase64 } from '$lib/utils/encoding';
	import { normalizeExitReason } from '$lib/utils/dev-runner-exit-reason';
	import { shouldSkipInjectedLine } from '$lib/dev-runner/log-dedup.js';
	import type {
		DevRunnerRunStatusResponse,
		DevRunnerPlanFileResponse,
		CurrentTrackingResponse
	} from '$lib/api';
	import { fetchPlans as storeFetchPlans, plansStore } from '$lib/stores/devRunnerPlans';

	let { initialPlan = '', initialRunner = '' }: { initialPlan?: string; initialRunner?: string } = $props();

	let runStatus = $state<DevRunnerRunStatusResponse | null>(null);
	let plans = $derived($plansStore);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let prevRunning = $state(false);
	let prevCycle = $state<number | null>(null);
	let showModal = $state(false);
	let taskHistoryOpen = $state(false);
	let taskHistoryTab = $state<'tasks' | 'plans' | 'merge' | 'logs'>('plans');
	let mergeQueuedCount = $state(0);
	const sidePanelTabs = $derived([
		{ id: 'plans', label: 'Plans', shortLabel: 'Plans' },
		{ id: 'tasks', label: 'Tasks', shortLabel: 'Tasks' },
		{ id: 'merge', label: 'Merge', shortLabel: 'Merge', count: mergeQueuedCount || undefined },
		{ id: 'logs', label: 'Logs', shortLabel: 'Logs' }
	]);
	let currentTracking = $state<CurrentTrackingResponse | null>(null);
	let selectedPlanPath = $state('');
	let taskListRefreshTick = $state(0);
	let planPreviewOpen = $state(false);
	let planPreviewPath = $state('');
	let planPreviewTitle = $state<string | null>(null);
	let planPreviewContextRunnerId = $state<string | null>(null);
	let planPreviewContextPlanPath = $state<string | null>(null);

	// Phase 2: Plan 상세 모달
	let modalPlan = $state<DevRunnerPlanFileResponse | null>(null);
	let modalMode = $state<'single' | 'all'>('single');
	let summaryGenerating = $state(false);
	let summaryGenerated = $state(false);
	let summaryGeneratedTimer: ReturnType<typeof setTimeout> | null = null;
	let summaryGenerationVersion = 0;

	function clearSummaryGeneratedTimer() {
		if (!summaryGeneratedTimer) return;
		clearTimeout(summaryGeneratedTimer);
		summaryGeneratedTimer = null;
	}

	function isArchivedPlanPath(path: string): boolean {
		return path.includes('/archive/') || path.includes('\\archive\\');
	}

	function resetPlanSummaryState() {
		summaryGenerationVersion += 1;
		summaryGenerating = false;
		summaryGenerated = false;
		clearSummaryGeneratedTimer();
	}

	function openExecutionModal() {
		modalPlan = null;
		modalMode = 'single';
		resetPlanSummaryState();
		if (selectedPlanPath && isArchivedPlanPath(selectedPlanPath)) {
			selectedPlanPath = '';
		}
		showModal = true;
	}

	function closeModal() {
		showModal = false;
		modalPlan = null;
		modalMode = 'single';
		closePlanPreview();
		resetPlanSummaryState();
	}

	async function handleGenerateSummary() {
		if (!modalPlan || summaryGenerating) return;
		const planPath = modalPlan.path;
		const requestVersion = summaryGenerationVersion + 1;
		summaryGenerationVersion = requestVersion;
		summaryGenerating = true;
		summaryGenerated = false;
		clearSummaryGeneratedTimer();
		try {
			await devRunnerPlanApi.generateSummary(encodePathToBase64(planPath));
			const updatedPlans = await fetchPlans();
			if (requestVersion !== summaryGenerationVersion) return;
			// modalPlan summary 갱신
			const updated = updatedPlans.find(p => p.path === planPath) ?? $plansStore.find(p => p.path === planPath);
			if (updated && modalPlan && modalPlan.path === planPath) modalPlan = updated;
			summaryGenerated = true;
			clearSummaryGeneratedTimer();
			summaryGeneratedTimer = setTimeout(() => {
				if (requestVersion !== summaryGenerationVersion) return;
				summaryGenerated = false;
				summaryGeneratedTimer = null;
			}, 2000);
		} catch (e) {
			console.warn('[DevRunner] generateSummary 실패', e);
		} finally {
			if (requestVersion === summaryGenerationVersion) {
				summaryGenerating = false;
			}
		}
	}

	// Phase 3: Runner 영역 구조 개편
	let runnerCardCollapsed = $state(false);

	// Phase 4: 종료 시 상태 보존
	let lastPlanFile = $state<string | null>(null);

	// SSE 로그 이벤트 라우팅용 LogViewer ref Map
	interface LogViewerRef {
		injectLine: (text: string | { text: string; meta?: Record<string, unknown> }) => void;
		injectCompleted: (reason?: string) => void;
		injectMergeCompleted: (reason?: string, status?: string) => void;
		catchUp?: () => Promise<void>;
	}
	const logRefs = new Map<string, LogViewerRef>();
	const injectedLineFingerprints = new Map<string, string[]>();
	const INJECT_LINE_DEDUP_LIMIT = 160;

	function catchUpRunnerLogRef(runnerId: string, ref: LogViewerRef | undefined = logRefs.get(runnerId)) {
		if (!ref) return;
		const tab = runnerTabs.find(t => t.id === runnerId);
		if (!tab) return;
		if (tab.running || activeTabId === runnerId) {
			void ref.catchUp?.();
		}
	}

	function catchUpVisibleRunnerRefs(runners: RunnerSource[]) {
		for (const runner of runners) {
			catchUpRunnerLogRef(runner.runner_id);
		}
	}

	function handlePlanModalOpen(plan: DevRunnerPlanFileResponse) {
		resetPlanSummaryState();
		modalPlan = plan;
		selectedPlanPath = plan.path;
		modalMode = 'single';
		showModal = true;
		if (window.innerWidth < 640) {
			taskHistoryOpen = false;
		}
	}

	function openPlanPreview(path: string | null | undefined, title?: string | null) {
		if (!path) return;
		planPreviewPath = path;
		planPreviewTitle = title ?? path.split(/[\\/]/).pop() ?? null;
		planPreviewContextRunnerId = activeTabId;
		planPreviewContextPlanPath = path;
		planPreviewOpen = true;
		if (window.innerWidth < 640) {
			taskHistoryOpen = false;
		}
	}

	function closePlanPreview() {
		planPreviewOpen = false;
		planPreviewPath = '';
		planPreviewTitle = null;
		planPreviewContextRunnerId = null;
		planPreviewContextPlanPath = null;
	}

	function handlePlanPreviewOpen(plan: DevRunnerPlanFileResponse) {
		openPlanPreview(plan.path, plan.filename);
	}

	// Merge 탭 대기 건수 뱃지 (MergeQueuePanel onCountChange 콜백으로 갱신)

	function handleMergeQueueCount(count: number) {
		mergeQueuedCount = count;
	}

	// Batch plan 상태 (LogViewer SSE에서 수신)
	let batchPlans = $state<{ name: string; status: 'pending' | 'running' | 'done' }[]>([]);

	// Runner 탭 관리 (멀티 runner 지원)
	interface RunnerTab {
		id: string;
		plan_file: string | null;
		engine: string | null;
		running: boolean;
		start_time: string | null;
		branch?: string | null;
		worktree_path?: string | null;
		merge_status?: string | null;
		merge_reason?: string | null;
		merge_message?: string | null;
		stop_stage?: string | null;
		trigger?: string | null;
		orphan?: boolean;
		orphan_alive?: boolean;
		redis_missing?: boolean;
		log_file_found?: boolean;
		exit_reason?: string | null;
		error?: string | null;
		display_plan_name?: string | null;
		execution_count?: number | null;
		remaining_post_merge_tasks?: number | null;
		merge_evidence_missing?: boolean | null;
		worktree_exists?: boolean | 'unknown';
		branch_exists?: boolean | 'unknown';
		branch_merged_to_main?: boolean | 'unknown';
		metadata_checked_at?: string | null;
		display_state?: string;
		display_label?: string;
		display_severity?: 'info' | 'warn' | 'error' | 'approval' | 'success' | 'muted';
		display_secondary?: string | null;
		hide_stale_branch_badge?: boolean;
	}

	interface RunnerSource {
		runner_id: string;
		plan_file?: string | null;
		engine?: string | null;
		running?: boolean;
		status?: string;
		pid?: number | string | null;
		current_cycle?: number | string | null;
		start_time?: string | null;
		branch?: string | null;
		worktree_path?: string | null;
		merge_status?: string | null;
		merge_reason?: string | null;
		merge_message?: string | null;
		stop_stage?: string | null;
		trigger?: string | null;
		orphan?: boolean;
		orphan_alive?: boolean;
		redis_missing?: boolean;
		log_file_found?: boolean;
		exit_reason?: string | null;
		error?: string | null;
		visible?: boolean;
		display_plan_name?: string | null;
		execution_count?: number | null;
		remaining_post_merge_tasks?: number | null;
		merge_evidence_missing?: boolean | null;
		worktree_exists?: boolean | 'unknown';
		branch_exists?: boolean | 'unknown';
		branch_merged_to_main?: boolean | 'unknown';
		metadata_checked_at?: string | null;
		display_state?: string;
		display_label?: string;
		display_severity?: 'info' | 'warn' | 'error' | 'approval' | 'success' | 'muted';
		display_secondary?: string | null;
		hide_stale_branch_badge?: boolean;
	}

	function createRunnerTab(runner: RunnerSource): RunnerTab {
		return {
			id: runner.runner_id,
			plan_file: runner.plan_file ?? null,
			engine: runner.engine ?? null,
			running: runner.running ?? runner.status === 'running',
			start_time: runner.start_time ? new Date(runner.start_time).toISOString() : null,
			branch: runner.branch ?? null,
			worktree_path: runner.worktree_path ?? null,
			merge_status: runner.merge_status ?? null,
			merge_reason: runner.merge_reason ?? null,
			merge_message: runner.merge_message ?? null,
			stop_stage: runner.stop_stage ?? null,
			trigger: runner.trigger ?? null,
			orphan: runner.orphan ?? false,
			orphan_alive: runner.orphan_alive ?? false,
			redis_missing: runner.redis_missing ?? false,
			log_file_found: runner.log_file_found ?? false,
			exit_reason: runner.exit_reason ?? undefined,
			error: runner.error ?? undefined,
			display_plan_name: runner.display_plan_name ?? null,
			execution_count: runner.execution_count ?? null,
			remaining_post_merge_tasks: runner.remaining_post_merge_tasks ?? null,
			merge_evidence_missing: runner.merge_evidence_missing ?? null,
			worktree_exists: runner.worktree_exists ?? 'unknown',
			branch_exists: runner.branch_exists ?? 'unknown',
			branch_merged_to_main: runner.branch_merged_to_main ?? 'unknown',
			metadata_checked_at: runner.metadata_checked_at ?? 'unknown',
			display_state: runner.display_state ?? 'stopped',
			display_label: runner.display_label ?? '중지됨',
			display_severity: runner.display_severity ?? 'muted',
			display_secondary: runner.display_secondary ?? null,
			hide_stale_branch_badge: runner.hide_stale_branch_badge ?? false,
		};
	}

	type EventLinePayload = string | { text: string; meta?: Record<string, unknown> };
	type CompletionEventSource = 'log_completed' | 'merge_log_completed';

	interface CompletionUpdatePayload {
		runner_id: string;
		reason?: string | null;
		status?: string | null;
		error?: string | null;
		source: CompletionEventSource;
	}

	function clearRunnerDedup(runnerId: string) {
		injectedLineFingerprints.delete(runnerId);
	}

	function normalizeEventLine(payload: unknown): string {
		if (typeof payload === 'string') return payload;
		if (
			payload &&
			typeof payload === 'object' &&
			'text' in (payload as Record<string, unknown>) &&
			typeof (payload as { text?: unknown }).text === 'string'
		) {
			return (payload as { text: string }).text;
		}
		if (payload == null) return '';
		return String(payload);
	}

	function isFailedExitReason(reason?: string | null): boolean {
		if (!reason) return false;
		const normalized = normalizeExitReason(reason);
		return !['completed', 'stopped', 'archived', 'on_hold', 'unknown'].includes(normalized);
	}

	function resolveCompletionReason(
		currentReason: string | null | undefined,
		incomingReason: string | null | undefined,
		incomingStatus: string | null | undefined,
		source: CompletionEventSource
	): string {
		const normalizedCurrent = currentReason ? normalizeExitReason(currentReason) : null;
		const normalizedIncoming = incomingReason ? normalizeExitReason(incomingReason) : null;
		const statusFailed = incomingStatus === 'failed';

		let candidate = normalizedIncoming;
		if (!candidate && statusFailed && source === 'merge_log_completed') {
			candidate = 'merge_failed';
		}
		if (!candidate && incomingStatus === 'success') {
			candidate = 'completed';
		}

		// 실패 reason은 success/completed 후속 이벤트보다 우선한다.
		if (isFailedExitReason(candidate) || statusFailed) {
			return candidate ?? normalizedCurrent ?? 'unknown';
		}
		if (isFailedExitReason(normalizedCurrent)) {
			return normalizedCurrent ?? 'unknown';
		}
		return candidate ?? normalizedCurrent ?? 'unknown';
	}

	function applyCompletionUpdate(payload: CompletionUpdatePayload): string {
		let resolvedReason = resolveCompletionReason(
			null,
			payload.reason ?? null,
			payload.status ?? null,
			payload.source
		);

		runnerTabs = runnerTabs.map(tab => {
			if (tab.id !== payload.runner_id) return tab;
			resolvedReason = resolveCompletionReason(
				tab.exit_reason ?? null,
				payload.reason ?? null,
				payload.status ?? null,
				payload.source
			);
			return {
				...tab,
				running: false,
				exit_reason: resolvedReason,
				error: payload.error ?? tab.error ?? null,
			};
		});

		return resolvedReason;
	}

	const isAllPlansSentinel = (f: string | null | undefined) =>
		f === '__ALL_PLANS__' || f === 'ALL';

	function updateRunnerTab(tab: RunnerTab, runner: RunnerSource): RunnerTab {
		return {
			...tab,
			running: runner.running ?? runner.status === 'running',
			plan_file: (!runner.plan_file || isAllPlansSentinel(runner.plan_file)) ? tab.plan_file : runner.plan_file,
			engine: (runner.engine ?? tab.engine) ?? null,
			start_time: (runner.start_time ?? tab.start_time) ?? null,
			branch: runner.branch ?? tab.branch ?? null,
			worktree_path: runner.worktree_path ?? tab.worktree_path ?? null,
			merge_status: runner.merge_status ?? tab.merge_status ?? null,
			stop_stage: runner.stop_stage ?? tab.stop_stage ?? null,
			orphan: runner.orphan ?? tab.orphan ?? false,
			orphan_alive: runner.orphan_alive ?? tab.orphan_alive ?? false,
			redis_missing: runner.redis_missing ?? tab.redis_missing ?? false,
			log_file_found: runner.log_file_found ?? tab.log_file_found ?? false,
			exit_reason: runner.exit_reason ?? tab.exit_reason ?? undefined,
			error: runner.error ?? tab.error ?? undefined,
			execution_count: runner.execution_count ?? tab.execution_count ?? null,
			worktree_exists: runner.worktree_exists ?? tab.worktree_exists ?? 'unknown',
			branch_exists: runner.branch_exists ?? tab.branch_exists ?? 'unknown',
			branch_merged_to_main: runner.branch_merged_to_main ?? tab.branch_merged_to_main ?? 'unknown',
			metadata_checked_at: runner.metadata_checked_at ?? tab.metadata_checked_at ?? 'unknown',
			display_state: runner.display_state ?? tab.display_state ?? 'stopped',
			display_label: runner.display_label ?? tab.display_label ?? '중지됨',
			display_severity: runner.display_severity ?? tab.display_severity ?? 'muted',
			display_secondary: runner.display_secondary ?? tab.display_secondary ?? null,
			hide_stale_branch_badge: runner.hide_stale_branch_badge ?? tab.hide_stale_branch_badge ?? false,
		};
	}

	function isVisibleRunnerSource(runner: RunnerSource): boolean {
		if (typeof runner.visible === 'boolean') {
			return runner.visible;
		}
		return runner.trigger === 'user' || runner.trigger === 'user:all';
	}

	function preserveMissingRunnerTab(tab: RunnerTab): RunnerTab {
		const next = {
			...tab,
			running: false,
			orphan_alive: tab.orphan_alive ?? false,
			redis_missing: true,
			log_file_found: tab.log_file_found ?? false,
		};
		catchUpRunnerLogRef(tab.id);
		return next;
	}

	function applyRunnersSync(
		allRunners: RunnerSource[],
		opts: { selectActive?: boolean } = {}
	): RunnerSource[] {
		const runners = allRunners.filter(isVisibleRunnerSource);
		const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
		const visibleIds = new Set(runners.map(r => r.runner_id));
		for (const cachedRunnerId of injectedLineFingerprints.keys()) {
			if (!visibleIds.has(cachedRunnerId)) {
				injectedLineFingerprints.delete(cachedRunnerId);
			}
		}

		runnerTabs = runnerTabs.map(tab => {
			const runner = runnerMap.get(tab.id);
			return runner ? updateRunnerTab(tab, runner) : preserveMissingRunnerTab(tab);
		});
		for (const runner of runners) {
			if (!runnerTabs.some(t => t.id === runner.runner_id)) {
				runnerTabs = [...runnerTabs, createRunnerTab(runner)];
			}
		}

		if (opts.selectActive !== false && !activeTabId && runnerTabs.length > 0) {
			activeTabId = runnerTabs[runnerTabs.length - 1].id;
		}
		catchUpVisibleRunnerRefs(runners);
		return runners;
	}

	function injectRunnerLine(runnerId: string, payload: EventLinePayload) {
		const normalizedLine = normalizeEventLine(payload);
		if (shouldSkipInjectedLine(injectedLineFingerprints, runnerId, normalizedLine, INJECT_LINE_DEDUP_LIMIT)) return;
		logRefs.get(runnerId)?.injectLine(normalizedLine);
	}

	async function syncRunnerTabs(opts: { selectActive?: boolean } = {}): Promise<RunnerSource[]> {
		try {
			const allRunners = await devRunnerRunnerApi.runners();
			return applyRunnersSync(allRunners, opts);
		} catch (e) {
			console.warn('[DevRunner] runners API 호출 실패', e);
			return [];
		}
	}

	let runnerTabs = $state<RunnerTab[]>([]);
	let activeTabId = $state<string | null>(null);

	// Phase 2: URL 동기화 준비 완료 플래그 (onMount 완료 전 $effect 실행 방지)
	let isReady = $state(false);

	// Phase 2: activeTabId 변경 시 URL ?runner= 파라미터 동기화
	$effect(() => {
		if (!isReady) return; // onMount 완료 전 skip (race condition 방지)
		const currentRunner = $page.url.searchParams.get('runner');
		if (activeTabId === currentRunner) return; // 이미 동기화됨
		const url = new URL($page.url.toString());
		if (activeTabId) {
			url.searchParams.set('runner', activeTabId);
		} else {
			url.searchParams.delete('runner');
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	});

	// Phase 1: elapsed 타이머
	let elapsed = $state('00:00:00');
	let elapsedInterval: ReturnType<typeof setInterval> | null = null;

	// SSE 연결 상태
	let eventSource: { close: () => void } | null = null;
	let sseConnected = $state(false);
	let sseReconnectDelay = 1000; // 지수 백오프 초기값
	let sseReconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let fallbackTimer: ReturnType<typeof setInterval> | null = null;

	function updateElapsed(startTime: string) {
		const diff = Date.now() - new Date(startTime).getTime();
		const h = Math.floor(diff / 3600000);
		const m = Math.floor((diff % 3600000) / 60000);
		const s = Math.floor((diff % 60000) / 1000);
		elapsed = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	}

	async function pollStatus() {
		try {
			const status = await devRunnerRunnerApi.status();
			runStatus = status;

			if (status.plan_file) {
				lastPlanFile = status.plan_file;
			}

			await syncRunnerTabs({ selectActive: true });
		} catch (e) {
			console.warn('[DevRunner] status API 호출 실패', e);
		}
	}

	// ── SSE 연결 ────────────────────────────────────────────────────────────
	// 재현 체크리스트(실시간 정지 후 새로고침 시 반영):
	// 1) /events SSE 연결 상태에서 특정 runner 로그가 증가하는지 확인
	// 2) Redis pub/sub 지연/공백을 유도한 뒤 sseConnected=true 상태에서 실시간 라인 정지 여부 관찰
	// 3) 같은 runner 탭에서 새로고침(loadRecent) 없이 라인이 재개되는지 확인
	// 4) 정지 시점과 재개 시점의 runner_id/engine/sseConnected를 함께 기록

	function handleSSEError() {
		sseConnected = false;
		eventSource?.close();
		eventSource = null;

		// 지수 백오프 재연결
		if (sseReconnectTimer) clearTimeout(sseReconnectTimer);
		sseReconnectTimer = setTimeout(() => {
			sseReconnectDelay = Math.min(sseReconnectDelay * 2, 30000);
			connectSSE();
		}, sseReconnectDelay);

		// fallback 폴링 시작 (10초 후)
		if (!fallbackTimer) {
			fallbackTimer = setInterval(async () => {
				if (!sseConnected) {
					void pollStatus();
				} else {
					if (fallbackTimer) {
						clearInterval(fallbackTimer);
						fallbackTimer = null;
					}
				}
			}, 30000);
			// 첫 fallback은 10초 후
			setTimeout(() => { if (!sseConnected) void pollStatus(); }, 10000);
		}
	}

	function handleSSEEvent(eventName: string, data: string) {
		if (eventName === 'status') {
			try {
				const parsed = JSON.parse(data) as {
					runners: {
						runner_id: string;
						status: string;
						pid: string | null;
						current_cycle: string | null;
						start_time: string | null;
						plan_file: string | null;
						engine: string | null;
						branch?: string | null;
						worktree_path?: string | null;
						merge_status?: string | null;
						stop_stage?: string | null;
						trigger?: string | null;
						exit_reason?: string | null;
						error?: string | null;
						visible?: boolean;
					}[];
				};
				// runner 종료 감지를 위해 업데이트 전 running 상태 캡처
				const prevRunningIds = new Set(runnerTabs.filter(t => t.running).map(t => t.id));
				const runners = applyRunnersSync(parsed.runners ?? [], { selectActive: true });
				const runningRunner = runners.find(r => r.status === 'running');
				const anyRunner = runners[0];
				const r = runningRunner ?? anyRunner;
				if (r) {
					runStatus = {
						...(runStatus ?? {} as DevRunnerRunStatusResponse),
						running: r.status === 'running',
						pid: r.pid != null ? Number(r.pid) : null,
						current_cycle: r.current_cycle != null ? Number(r.current_cycle) : null,
						start_time: r.start_time ?? null,
						plan_file: r.plan_file ?? null,
						runner_id: r.runner_id,
					} as DevRunnerRunStatusResponse;
				} else if (runners.length === 0 && runStatus) {
					runStatus = { ...runStatus, running: false };
					// runner 목록이 완전히 사라진 경우 (프로세스 종료 + Redis 정리 완료)
					if (prevRunningIds.size > 0) {
						void fetchPlans();
						taskListRefreshTick++;
					}
				}
				if (runners.length > 0) {
					// running → stopped 전이 감지: 이전에 running이었던 runner가 stopped이거나 사라진 경우
					const anyBecameStopped = [...prevRunningIds].some(id => {
						const tab = runnerTabs.find(t => t.id === id);
						return !tab || !tab.running;
					});
					if (anyBecameStopped) {
						void fetchPlans();
						taskListRefreshTick++;
					}
				}
			} catch {
				// JSON 파싱 오류 무시
			}
		} else if (eventName === 'tracking') {
			try {
				currentTracking = JSON.parse(data) as CurrentTrackingResponse;
			} catch {
				// 무시
			}
		} else if (eventName === 'plan_changed') {
			void fetchPlans();
			taskListRefreshTick++;
		} else if (eventName === 'log') {
			try {
				const { runner_id, line } = JSON.parse(data) as { runner_id: string; line: EventLinePayload };
				injectRunnerLine(runner_id, line);
			} catch { /* 무시 */ }
		} else if (eventName === 'log_completed') {
			try {
				const { runner_id, reason, status, error } = JSON.parse(data) as {
					runner_id: string;
					reason?: string | null;
					status?: string | null;
					error?: string | null;
				};
				const resolvedReason = applyCompletionUpdate({
					runner_id,
					reason: reason ?? null,
					status: status ?? null,
					error: error ?? null,
					source: 'log_completed',
				});
				logRefs.get(runner_id)?.injectCompleted(resolvedReason);
			} catch { /* 무시 */ }
		} else if (eventName === 'merge_log') {
			try {
				const { runner_id, line } = JSON.parse(data) as { runner_id: string; line: EventLinePayload };
				injectRunnerLine(runner_id, line);
			} catch { /* 무시 */ }
		} else if (eventName === 'merge_log_completed') {
			try {
				const { runner_id, reason, status } = JSON.parse(data) as {
					runner_id: string;
					reason?: string | null;
					status?: string | null;
				};
				const resolvedReason = applyCompletionUpdate({
					runner_id,
					reason: reason ?? null,
					status: status ?? null,
					source: 'merge_log_completed',
				});
				logRefs.get(runner_id)?.injectMergeCompleted(resolvedReason, status ?? undefined);
			} catch { /* 무시 */ }
		}
	}

	function connectSSE() {
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}

		eventSource = devRunnerEventApi.connectEvents({
			onOpen: () => {
				sseConnected = true;
				sseReconnectDelay = 1000; // 성공 시 delay 리셋
				if (fallbackTimer) {
					clearInterval(fallbackTimer);
					fallbackTimer = null;
				}
				// SSE 재연결 시 running 탭에 catch-up 신호 전달
				for (const [id, ref] of logRefs) {
					catchUpRunnerLogRef(id, ref);
				}
			},
			onError: handleSSEError,
			onEvent: handleSSEEvent
		});
	}

	function handleRunSuccess(response: DevRunnerRunStatusResponse) {
		if (!response.runner_id) return;
		// runStatus 즉시 업데이트 (시작 API 응답에서 확보) — 상단 바 "실행 중" 즉시 표시
		runStatus = response;
		const responseTrigger = (response as { trigger?: string | null }).trigger ?? 'user';
		const newTab: RunnerTab = {
			...createRunnerTab({
				runner_id: response.runner_id,
				plan_file: response.plan_file,
				engine: response.engine,
				start_time: response.start_time,
				trigger: responseTrigger,
			}),
			running: true,
		};
		runnerTabs = [...runnerTabs, newTab];
		activeTabId = response.runner_id;
		if (window.innerWidth < 640) {
			taskHistoryOpen = false;
		} else {
			taskHistoryTab = 'tasks';
		}
	}

	function handleCloseTab(runnerId: string) {
		// 탭 제거는 dismiss(수동 닫기) 경로에서만 수행한다. sync 경로는 remove를 하지 않는다.
		// running이 아닌 탭은 서버에 dismiss 요청하여 다른 기기에서도 사라지게 함
		const tab = runnerTabs.find(t => t.id === runnerId);
		if (tab && !tab.running) {
			devRunnerRunnerApi.dismissTab(runnerId).catch(() => {
				// dismiss 실패해도 로컬 탭은 닫음
			});
		}
		logRefs.delete(runnerId);
		clearRunnerDedup(runnerId);
		runnerTabs = runnerTabs.filter(t => t.id !== runnerId);
		if (activeTabId === runnerId) {
			activeTabId = runnerTabs.length > 0 ? runnerTabs[runnerTabs.length - 1].id : null;
		}
	}

	function handleTabStop(runnerId: string) {
		runnerTabs = runnerTabs.map(t => t.id === runnerId ? { ...t, running: false } : t);
		void pollStatus();
	}

	async function handleRestart(tab: RunnerTab) {
		try {
			const response = await devRunnerRunnerApi.start({ plan_file: tab.plan_file, engine: tab.engine ?? undefined, trigger: 'user' });
			handleRunSuccess(response);
		} catch (e) {
			console.error('[DevRunner] 재실행 실패', e);
		}
	}

	async function fetchPlans(): Promise<DevRunnerPlanFileResponse[]> {
		try {
			return await storeFetchPlans();
		} catch (e) {
			console.warn('[DevRunner] plans API 호출 실패', e);
			return [];
		}
	}

	async function handleSync() {
		try {
			await devRunnerPlanApi.sync();
			await fetchPlans();
		} catch (e) {
			console.warn('[DevRunner] sync 실패', e);
		}
	}

	async function handleCleanup() {
		try {
			const result = await devRunnerRunnerApi.cleanupStale();
			await syncRunnerTabs({ selectActive: true });
			const msg = `정리 완료: ${result.cleaned}개 항목 제거`;
			console.info('[DevRunner]', msg, result.detail);
		} catch (e) {
			console.warn('[DevRunner] cleanup 실패', e);
		}
	}

	async function fetchRunners() {
		await syncRunnerTabs({ selectActive: true });
	}

	async function loadData() {
		await Promise.all([pollStatus(), fetchPlans()]);
		error = null;
	}

	function handleRunStart(response: DevRunnerRunStatusResponse) {
		handleRunSuccess(response);
	}

        async function handleRunStatusChange() {
		await pollStatus();
		void fetchPlans();
	}

	onMount(async () => {
                if (window.innerWidth >= 640) {
                        taskHistoryOpen = true;
                } else {
			runnerCardCollapsed = true;
		}

                // 초기 로드
                await Promise.all([pollStatus(), fetchPlans()]);

                // 모바일: 실행 중이면 패널 닫기 (panelOpen 제거됨 - taskHistoryOpen으로 대체)
                if (window.innerWidth < 640) {
                        taskHistoryOpen = !runStatus?.running;
                }
                loading = false;
                error = null;

		// Phase 1: initialRunner가 있으면 해당 탭으로 활성화
		if (initialRunner) {
			const SPECIAL_IDS = ['__logs__', '__merge__'];
			const exists = runnerTabs.some(t => t.id === initialRunner) || SPECIAL_IDS.includes(initialRunner);
			if (exists) {
				activeTabId = initialRunner;
			}
			// 존재하지 않는 ID는 무시 (기존 activeTabId 유지)
		}

		// Phase 2: onMount 완료 — URL 동기화 $effect 활성화
		isReady = true;

		// Phase 4: initialPlan이 있으면 자동 실행
		if (initialPlan) {
			try {
				const decodedPath = atob(initialPlan);
				const initResponse = await devRunnerRunnerApi.start({ plan_file: decodedPath, trigger: 'user' });
				handleRunStart(initResponse);
				await pollStatus();
				// Phase 3: URL에서 plan param 제거, runner param 동시 설정
				const url = new URL(window.location.href);
				url.searchParams.delete('plan');
				if (initResponse.runner_id) {
					url.searchParams.set('runner', initResponse.runner_id);
				}
				goto(url.toString(), { replaceState: true, keepFocus: true });
			} catch (e) {
				console.warn('[DevRunner] initialPlan 자동 실행 실패', e);
			}
		}

		// SSE 연결 (폴링 대체)
		connectSSE();
	});

	onDestroy(() => {
		// SSE 정리
		if (sseReconnectTimer) {
			clearTimeout(sseReconnectTimer);
			sseReconnectTimer = null;
		}
		if (fallbackTimer) {
			clearInterval(fallbackTimer);
			fallbackTimer = null;
		}
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}
		sseConnected = false;

		if (elapsedInterval) {
			clearInterval(elapsedInterval);
			elapsedInterval = null;
		}
		clearSummaryGeneratedTimer();
		injectedLineFingerprints.clear();
		});


	$effect(() => {
		if (activeTabId) {
			catchUpRunnerLogRef(activeTabId);
		}

		// current_cycle 변화 감지 → plans 갱신
		const currentCycle = runStatus?.current_cycle ?? null;
		if (currentCycle !== null && prevCycle !== null && currentCycle !== prevCycle) {
			void fetchPlans();
		}
		prevCycle = currentCycle;

		// 시작 감지 (runningCount 0 → 1+)
		if (!prevRunning && runningCount > 0) {
			lastPlanFile = null;
		}

		// 종료 감지 → 모든 runner 종료 시만 plans 갱신
		if (prevRunning && runningCount === 0) {
			void fetchPlans();
		}

		// elapsed 타이머 관리 (활성 탭 기준)
		if (activeTabRunner?.running && activeTabRunner.start_time) {
			updateElapsed(activeTabRunner.start_time);
			if (elapsedInterval) clearInterval(elapsedInterval);
			elapsedInterval = setInterval(() => updateElapsed(activeTabRunner!.start_time!), 1000);
		} else {
			if (elapsedInterval) {
				clearInterval(elapsedInterval);
				elapsedInterval = null;
			}
			elapsed = '00:00:00';
		}

		prevRunning = runningCount > 0;
	});

	// 파생 데이터
	let activeTabRunner = $derived(runnerTabs.find(t => t.id === activeTabId) ?? null);
	let runningCount = $derived(runnerTabs.filter(t => t.running).length);
	let effectivePlanFile = $derived(activeTabRunner?.plan_file ?? lastPlanFile);
	// TaskList에 표시할 plan path (활성 탭의 plan 또는 사용자가 선택한 plan)
	let taskListPlanPath = $derived(effectivePlanFile ?? selectedPlanPath ?? null);

	$effect(() => {
		if (!planPreviewOpen) return;
		if (planPreviewContextRunnerId !== activeTabId) {
			closePlanPreview();
			return;
		}
		if (
			planPreviewContextPlanPath &&
			taskListPlanPath &&
			planPreviewContextPlanPath !== taskListPlanPath &&
			planPreviewPath === planPreviewContextPlanPath
		) {
			closePlanPreview();
		}
	});
</script>

<div class="flex flex-col h-full overflow-hidden">

	<!-- Main content -->
	<div class="flex-1 min-h-0 flex flex-col sm:overflow-hidden">
		{#if error}
			<div class="mx-4 mt-2 bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-xs shrink-0">
				{error}
			</div>
		{/if}

		{#if loading}
			<div class="flex items-center justify-center py-20">
				<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
			</div>
		{:else}
			<!-- RunStatusBar -->
			<RunStatusBar
				runners={runnerTabs}
				{sseConnected}
				{runStatus}
				{elapsed}
				onSync={handleSync}
				onCleanup={handleCleanup}
				onExecute={() => { openExecutionModal(); }}
				onStopAll={runningCount > 0 ? async () => {
					for (const t of runnerTabs.filter(r => r.running)) {
						await devRunnerRunnerApi.stop(t.id).catch(() => {});
					}
					void pollStatus();
				} : undefined}
			onStopRunner={async (id) => { await devRunnerRunnerApi.stop(id).catch(() => {}); void pollStatus(); }}
			onKillRunner={async (id) => { await devRunnerRunnerApi.kill(id).catch(() => {}); void pollStatus(); }}
			collapsed={runnerCardCollapsed}
			onToggleCollapse={() => { runnerCardCollapsed = !runnerCardCollapsed; }}
			activeRunnerId={activeTabId}
			onSelectRunner={(id) => { activeTabId = id; }}
			onCloseAllTerminated={() => { for (const t of runnerTabs.filter(r => !r.running)) { handleCloseTab(t.id); } }}
			onShowLogs={() => { activeTabId = '__logs__'; }}
			onCloseRunner={handleCloseTab}
			/>

			<!-- 단일 실행 모달 -->
			<RunControl
				open={showModal}
				onClose={closeModal}
				plan={modalPlan}
				summaryGenerating={summaryGenerating}
				summaryGenerated={summaryGenerated}
				onGenerateSummary={handleGenerateSummary}
				status={runStatus}
				{plans}
				onStatusChange={async () => { closeModal(); await handleRunStatusChange(); }}
				onStart={(r) => { closeModal(); handleRunStart(r); }}
				bind:selectedPlan={selectedPlanPath}
				bind:mode={modalMode}
				runnerTabs={runnerTabs.map(t => ({ id: t.id, running: t.running }))}
				hidePlanSelector={modalPlan != null}
			/>

			<!-- 모바일 액션 바 (sm 미만에서만 표시) -->
			<div class="flex items-center gap-2 sm:hidden shrink-0 px-2 pb-1">
				<div class="min-w-0 flex-1">
					<TabNav
						tabs={sidePanelTabs}
						bind:activeTab={taskHistoryTab}
						variant="secondary"
						size="compact"
						onTabChange={() => { taskHistoryOpen = true; }}
					/>
				</div>
				<button
					onclick={() => { openExecutionModal(); }}
					class="flex items-center justify-center h-8 w-8 border border-border rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground shrink-0"
					title="Execute"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
				</button>
				<!-- 종료된 탭 일괄 닫기 -->
				{#if runnerTabs.some(t => !t.running)}
					<button
						onclick={() => { for (const t of runnerTabs.filter(r => !r.running)) { handleCloseTab(t.id); } }}
						class="flex items-center justify-center h-8 w-8 border border-red-200 rounded-md hover:bg-red-100 transition-colors text-red-400 hover:text-red-600 shrink-0"
						title="종료된 runner 탭 모두 닫기"
					>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
					</button>
				{/if}
			</div>

			<!-- 모바일: 좌측 패널 오버레이 -->
			{#if taskHistoryOpen}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-40 bg-black/30 sm:hidden"
					onclick={() => { taskHistoryOpen = false; }}
					role="presentation"
				></div>
			{/if}

			<!-- 2컬럼 레이아웃: 좌측 패널 + 우측 Runner 영역 -->
			<div class="flex-1 min-h-0 flex gap-2 p-2 sm:p-3 overflow-hidden">

				<!-- 좌측 패널: Plans/Tasks/Merge/설정 (모바일=오버레이, 데스크톱=고정) -->
				<div class="
					{taskHistoryOpen ? 'flex' : 'hidden'} sm:flex
					flex-col min-h-0 overflow-hidden
					w-[300px] sm:w-[340px] shrink-0
					fixed sm:static inset-y-0 left-0 z-50 sm:z-auto
					bg-card rounded-md border border-border
				">
					<div class="flex items-center gap-2 border-b border-border p-2 shrink-0">
						<div class="min-w-0 flex-1">
							<TabNav tabs={sidePanelTabs} bind:activeTab={taskHistoryTab} variant="secondary" size="compact" />
						</div>
						<button
							onclick={() => { taskHistoryOpen = false; }}
							class="sm:hidden p-1 rounded-md hover:bg-secondary text-muted-foreground transition-colors shrink-0"
							title="Close"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
						</button>
					</div>
					<!-- 탭 콘텐츠: flex flex-col 필수 (하위 flex-1 높이 전파 — 제거 금지) -->
					<div class="flex-1 min-h-0 flex flex-col overflow-hidden">
						{#if taskHistoryTab === 'tasks'}
							<div class="px-4 pb-4 flex-1 min-h-0 flex flex-col overflow-hidden">
								{#if currentTracking}
									<div class="shrink-0">
										<CurrentTrackingCard tracking={currentTracking} />
									</div>
								{/if}
								<div class="flex-1 min-h-0 flex flex-col overflow-hidden">
									<TaskList
										planPath={taskListPlanPath}
										refreshTick={taskListRefreshTick}
										onOpenPlanPreview={openPlanPreview}
									/>
								</div>
							</div>
						{:else if taskHistoryTab === 'plans'}
							<div class="px-4 pb-4 flex-1 min-h-0 overflow-hidden flex flex-col">
								<PlanList
									{plans}
									onPlansChange={fetchPlans}
									runningPlanFile={runStatus?.plan_file ?? null}
									{lastPlanFile}
									{batchPlans}
									onPlanModalOpen={handlePlanModalOpen}
									onPlanPreviewOpen={handlePlanPreviewOpen}
								/>
							</div>
						{:else if taskHistoryTab === 'merge'}
							<div class="h-full min-h-0 flex flex-col overflow-hidden">
								<div class="min-h-0 flex-[3] overflow-hidden">
									<MergeQueuePanel onCountChange={handleMergeQueueCount} />
								</div>
								<div class="min-h-0 flex-[2] overflow-hidden border-t border-border">
									<WorkflowList />
								</div>
							</div>
						{:else if taskHistoryTab === 'logs'}
							<div class="h-full min-h-0 overflow-hidden">
								<LogHistoryPanel />
							</div>
						{/if}
					</div>
				</div>

				{#if planPreviewOpen && planPreviewPath}
					<div class="hidden lg:flex w-[min(46vw,720px)] min-w-[420px] max-w-[720px] min-h-0 shrink-0 flex-col overflow-hidden">
						<PlanMarkdownPreview
							planPath={planPreviewPath}
							title={planPreviewTitle}
							onClose={closePlanPreview}
						/>
					</div>
				{/if}

				<!-- 우측 영역: Runner 탭 바 + Runner/Logs/Merge 콘텐츠 -->
				<div class="flex-1 min-h-0 flex flex-col overflow-hidden bg-card rounded-md border border-border">
					<!-- Runner 콘텐츠 -->
					<div class="flex-1 min-h-0 overflow-hidden">
						{#if activeTabId === '__logs__'}
							<UnifiedLogsView />
						{:else if activeTabId === '__merge__'}
							<MergeQueuePanel />
						{:else if runnerTabs.length === 0}
							<div class="flex items-center justify-center h-full text-muted-foreground font-mono text-xs">
								실행 버튼을 눌러 plan-runner를 시작하세요
							</div>
						{:else}
							{#each runnerTabs as tab (tab.id)}
								<div class="h-full {activeTabId === tab.id ? '' : 'hidden'}">
									<RunnerInstanceTab
										runnerId={tab.id}
										planFile={tab.plan_file}
										running={tab.running}
										engine={tab.engine}
										startTime={tab.start_time}
										worktreePath={tab.worktree_path}
										branch={tab.branch}
										mergeStatus={tab.merge_status}
										mergeReason={tab.merge_reason}
										mergeMessage={tab.merge_message}
										trigger={tab.trigger}
										orphan={tab.orphan}
										orphanAlive={tab.orphan_alive}
										redisMissing={tab.redis_missing}
										logFileFound={tab.log_file_found}
										exitReason={tab.exit_reason}
										error={tab.error}
										displayPlanName={tab.display_plan_name}
										remainingPostMergeTasks={tab.remaining_post_merge_tasks}
										mergeEvidenceMissing={tab.merge_evidence_missing}
										executionCount={tab.execution_count}
										worktreeExists={tab.worktree_exists}
										branchExists={tab.branch_exists}
										branchMergedToMain={tab.branch_merged_to_main}
										metadataCheckedAt={tab.metadata_checked_at}
										displayLabel={tab.display_label}
										displaySecondary={tab.display_secondary}
										hideStaleBranchBadge={tab.hide_stale_branch_badge}
										onStop={() => handleTabStop(tab.id)}
										onClose={() => handleCloseTab(tab.id)}
										onRestart={() => handleRestart(tab)}
										onBatchPlansChange={(plans) => { batchPlans = plans; }}
										logRef={(ref) => {
											logRefs.set(tab.id, ref);
											catchUpRunnerLogRef(tab.id, ref);
										}}
									/>
								</div>
							{/each}
						{/if}
					</div>
				</div>
			</div>

			{#if planPreviewOpen && planPreviewPath}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-[70] bg-black/40 lg:hidden"
					onclick={closePlanPreview}
					role="presentation"
				></div>
				<div class="fixed inset-0 z-[80] flex flex-col bg-card lg:hidden">
					<PlanMarkdownPreview
						planPath={planPreviewPath}
						title={planPreviewTitle}
						onClose={closePlanPreview}
					/>
				</div>
			{/if}
		{/if}

	</div>
</div>
