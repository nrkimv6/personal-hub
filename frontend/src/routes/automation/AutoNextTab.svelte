<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import StatsCard from '$lib/components/auto-next/StatsCard.svelte';
	import TaskList from '$lib/components/auto-next/TaskList.svelte';
	import RunControl from '$lib/components/auto-next/RunControl.svelte';
	import PlanList from '$lib/components/auto-next/PlanList.svelte';
	import LogViewer from '$lib/components/auto-next/LogViewer.svelte';
	import CurrentTrackingCard from '$lib/components/auto-next/CurrentTrackingCard.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import {
		autoNextStatsApi,
		autoNextTaskApi,
		autoNextRunnerApi,
		autoNextPlanApi
	} from '$lib/api';
	import type {
		AutoNextStatsResponse,
		AutoNextTaskListResponse,
		AutoNextRunStatusResponse,
		AutoNextPlanFileResponse,
		CurrentTrackingResponse
	} from '$lib/api';

	let stats = $state<AutoNextStatsResponse | null>(null);
	let currentRunStats = $state<AutoNextStatsResponse | null>(null);
	let taskList = $state<AutoNextTaskListResponse | null>(null);
	let runStatus = $state<AutoNextRunStatusResponse | null>(null);
	let plans = $state<AutoNextPlanFileResponse[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let statusFilter = $state<string | undefined>(undefined);
	let pollingController: ReturnType<typeof createSmartPolling> | null = null;
	let prevRunning = $state(false);
	let prevCycle = $state<number | null>(null);
	let justCompleted = $state(false);
	let completedTimer: ReturnType<typeof setTimeout> | null = null;
	let lastStartTime = $state<string | null>(null);
	let panelOpen = $state(true);
	let taskHistoryOpen = $state(true);
	let currentTracking = $state<CurrentTrackingResponse | null>(null);
	let trackingInterval: ReturnType<typeof setInterval> | null = null;

	// Phase 4: 종료 시 상태 보존
	let lastRunStats = $state<AutoNextStatsResponse | null>(null);
	let lastPlanFile = $state<string | null>(null);

	// Phase 1: elapsed 타이머 (RunControl에서 이동)
	let elapsed = $state('00:00:00');
	let elapsedInterval: ReturnType<typeof setInterval> | null = null;

	function updateElapsed(startTime: string) {
		const diff = Date.now() - new Date(startTime).getTime();
		const h = Math.floor(diff / 3600000);
		const m = Math.floor((diff % 3600000) / 60000);
		const s = Math.floor((diff % 60000) / 1000);
		elapsed = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	}

	async function pollStatus() {
		try {
			const status = await autoNextRunnerApi.status();
			runStatus = status;

			if (status.running && status.start_time) {
				lastStartTime = status.start_time;
				currentRunStats = await autoNextStatsApi.stats(status.start_time);
			} else if (!status.running) {
				// 종료 시 마지막 상태 보존
				if (currentRunStats) {
					lastRunStats = currentRunStats;
				}
				if (status.plan_file) {
					lastPlanFile = status.plan_file;
				}
				currentRunStats = null;
				lastStartTime = null;
			}
		} catch (e) {
			console.warn('[AutoNext] status API 호출 실패', e);
		}
	}

	async function fetchStats() {
		try {
			stats = await autoNextStatsApi.stats();
		} catch (e) {
			console.warn('[AutoNext] stats API 호출 실패', e);
		}
	}

	async function fetchTasks() {
		try {
			taskList = await autoNextTaskApi.list({
				status: statusFilter,
				limit: 50,
				source_path: runStatus?.plan_file ?? lastPlanFile ?? undefined
			});
		} catch (e) {
			console.warn('[AutoNext] tasks API 호출 실패', e);
		}
	}

	async function fetchPlans() {
		try {
			plans = await autoNextPlanApi.list();
		} catch (e) {
			console.warn('[AutoNext] plans API 호출 실패', e);
		}
	}

	async function loadData() {
		await Promise.all([pollStatus(), fetchStats(), fetchTasks(), fetchPlans()]);
		error = null;
	}

	function handleFilterChange(newFilter: string | undefined) {
		statusFilter = newFilter;
		void fetchTasks();
	}

	async function handleDeleteTask(id: string) {
		try {
			await autoNextTaskApi.delete(id);
			await fetchTasks();
			void fetchStats();
		} catch (e) {
			error = e instanceof Error ? e.message : '삭제 실패';
		}
	}

	async function handleDeleteCompleted() {
		try {
			await autoNextTaskApi.deleteCompleted(runStatus?.plan_file ?? lastPlanFile ?? undefined);
			await fetchTasks();
			void fetchStats();
		} catch (e) {
			error = e instanceof Error ? e.message : '일괄 삭제 실패';
		}
	}

	async function handleDeleteOld(hours: number) {
		try {
			await autoNextTaskApi.deleteOld(hours, runStatus?.plan_file ?? lastPlanFile ?? undefined);
			await fetchTasks();
			void fetchStats();
		} catch (e) {
			error = e instanceof Error ? e.message : '이력 정리 실패';
		}
	}

	async function handleRunStatusChange() {
		await pollStatus();
		void fetchStats();
		void fetchTasks();
	}

	onMount(async () => {
		// 초기 로드: 모든 데이터 병렬로 한 번에 가져오기
		await Promise.all([pollStatus(), fetchStats(), fetchTasks(), fetchPlans()]);
		loading = false;
		error = null;

		// 폴링은 status만 (3초/15초 간격)
		pollingController = createSmartPolling(
			pollStatus,
			() => ({ running: runStatus?.running ?? false })
		);

		// TaskTracker tracking 정보 폴링 (5초 간격, 실행 중일 때만 의미있음)
		trackingInterval = setInterval(async () => {
			try {
				currentTracking = await autoNextTaskApi.currentTracking();
			} catch {
				currentTracking = null;
			}
		}, 5000);
	});

	onDestroy(() => {
		if (pollingController) {
			pollingController.cleanup();
			pollingController = null;
		}
		if (elapsedInterval) {
			clearInterval(elapsedInterval);
			elapsedInterval = null;
		}
		if (trackingInterval) {
			clearInterval(trackingInterval);
			trackingInterval = null;
		}
	});

	$effect(() => {
		if (runStatus && pollingController) {
			pollingController.refresh();
		}

		// Phase 3: current_cycle 변화 감지 → stats + tasks 갱신 (fire-and-forget)
		const currentCycle = runStatus?.current_cycle ?? null;
		if (currentCycle !== null && prevCycle !== null && currentCycle !== prevCycle) {
			void fetchStats();
			void fetchTasks();
		}
		prevCycle = currentCycle;

		// Phase 4: 시작 감지 → 이전 데이터 청소 + stats/tasks 갱신
		if (runStatus && !prevRunning && runStatus.running) {
			lastRunStats = null;
			lastPlanFile = null;
			void fetchStats();
			void fetchTasks();
		}

		// 종료 감지 + stats/tasks 갱신
		if (runStatus && prevRunning && !runStatus.running) {
			justCompleted = true;
			if (completedTimer) clearTimeout(completedTimer);
			completedTimer = setTimeout(() => { justCompleted = false; }, 10000);
			void fetchStats();
			void fetchTasks();
		}

		// Phase 1: elapsed 타이머 관리
		if (runStatus?.running && runStatus.start_time) {
			updateElapsed(runStatus.start_time);
			if (elapsedInterval) clearInterval(elapsedInterval);
			elapsedInterval = setInterval(() => updateElapsed(runStatus!.start_time!), 1000);
		} else {
			if (elapsedInterval) {
				clearInterval(elapsedInterval);
				elapsedInterval = null;
			}
			elapsed = '00:00:00';
		}

		if (runStatus) prevRunning = runStatus.running;
	});

	// 파생 데이터
	let currentTask = $derived(taskList?.tasks?.find(t => t.status === 'running') ?? null);
	let activePlan = $derived(plans?.find(p => p.path === runStatus?.plan_file) ?? null);
	// Phase 4: 종료 후에도 plan 정보 유지
	let effectivePlanFile = $derived(runStatus?.plan_file ?? lastPlanFile);
	let effectiveRunStats = $derived(currentRunStats ?? lastRunStats);
</script>

<div class="flex flex-col h-full overflow-hidden">

	<!-- Main content -->
	<div class="flex-1 flex flex-col overflow-hidden">
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
			<!-- Collapsible Control Panel -->
			<div class="border-b">
				<!-- Collapsible trigger bar (always visible) -->
				<button
					onclick={() => (panelOpen = !panelOpen)}
					class="flex items-center justify-between w-full px-4 py-2.5 hover:bg-gray-50 transition-colors"
				>
					<div class="flex items-center gap-4 min-w-0">
						<!-- Status indicator (Phase 1: 통합 상태 표시) -->
						<div class="flex items-center gap-2 shrink-0">
							{#if runStatus?.running}
								<div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
								<span class="text-xs font-medium">실행 중</span>
								{#if runStatus?.pid}
									<span class="text-[10px] text-gray-500 font-mono">PID {runStatus.pid}</span>
								{/if}
								<span class="text-[10px] text-gray-500 flex items-center gap-1">
									<svg class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
									Cycle {runStatus.current_cycle ?? '-'}
								</span>
								<span class="text-[10px] text-gray-500 font-mono">{elapsed}</span>
							{:else if runStatus?.crashed}
								<div class="w-2 h-2 rounded-full bg-red-500"></div>
								<span class="text-xs font-medium text-red-700">비정상 종료</span>
							{:else if justCompleted}
								<div class="w-2 h-2 rounded-full bg-blue-500"></div>
								<span class="text-xs font-medium text-blue-700">완료됨</span>
							{:else}
								<div class="w-2 h-2 rounded-full bg-gray-400"></div>
								<span class="text-xs font-medium text-gray-600">대기</span>
							{/if}
						</div>

						<!-- Collapsed inline info -->
						{#if !panelOpen}
							<div class="flex items-center gap-3 min-w-0 overflow-hidden">
								<div class="h-3.5 w-px bg-gray-200 shrink-0"></div>

								<!-- Current plan -->
								{#if activePlan}
									<div class="flex items-center gap-1.5 shrink-0">
										<svg class="w-3 h-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
										<span class="text-xs text-gray-500 font-mono truncate max-w-[200px]">{activePlan.filename}</span>
										<span class="bg-blue-100 text-blue-700 border border-blue-200 text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded">
											{activePlan.progress.done}/{activePlan.progress.total}
										</span>
									</div>
								{:else if effectivePlanFile === 'ALL'}
									<span class="text-xs text-gray-500">전체 실행</span>
								{/if}

								<div class="h-3.5 w-px bg-gray-200 shrink-0"></div>

								<!-- Current task summary -->
								{#if currentTask}
									<span class="text-xs text-gray-600 truncate min-w-0">{currentTask.text.slice(0, 60)}...</span>
								{/if}

								<div class="h-3.5 w-px bg-gray-200 shrink-0"></div>

								<!-- Progress summary -->
								{#if stats}
									<div class="flex items-center gap-1.5 shrink-0">
										<span class="text-[10px] text-gray-500 font-mono">
											{stats.completed}/{stats.total} tasks
										</span>
										<span class="text-[10px] text-green-600 font-mono">
											{stats.success_rate.toFixed(0)}%
										</span>
									</div>
								{/if}
							</div>
						{/if}
					</div>
					<svg
						class="w-3.5 h-3.5 text-gray-400 shrink-0 transition-transform {panelOpen ? '' : 'rotate-180'}"
						viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
					>
						<path d="M18 15l-6-6-6 6" />
					</svg>
				</button>

				<!-- Expanded panel content -->
				{#if panelOpen}
					<div class="px-4 pb-4 flex flex-col gap-4 bg-gray-50 overflow-y-auto max-h-[calc(100vh-8rem)] sm:max-h-none sm:overflow-visible">
						<!-- RunControl - full width card -->
						<div class="bg-white border rounded-lg p-4">
							<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} />
						</div>

						<!-- Grid: Stats + Plans (Phase 3: CurrentTaskCard 제거) -->
						<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
							<!-- Stats -->
							<div class="bg-white border rounded-lg p-4">
								<div class="flex items-center gap-2 mb-3">
									<svg class="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
									<span class="text-xs font-medium uppercase tracking-wider">Statistics</span>
								</div>
								{#if stats}
									<StatsCard {stats} currentRunStats={effectiveRunStats} isRunning={runStatus?.running ?? false} />
								{/if}
							</div>

							<!-- Plan Files -->
							<div class="bg-white border rounded-lg p-4 max-h-[50vh] sm:max-h-[340px] overflow-hidden flex flex-col">
								<PlanList {plans} onPlansChange={fetchPlans} />
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Log Viewer + Task History -->
			<div class="flex flex-col flex-1 overflow-hidden">
				<!-- Log Viewer (Phase 2: planFile prop 전달) -->
				<div class="flex-1 min-h-0">
					<LogViewer planFile={effectivePlanFile ?? undefined} />
				</div>

				<!-- Task History (Phase 3: 기본 열림) -->
				<div class="shrink-0 border-t">
					<button
						onclick={() => (taskHistoryOpen = !taskHistoryOpen)}
						class="flex items-center gap-2 w-full px-4 py-2 hover:bg-gray-50 transition-colors"
					>
						<svg class="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
						<span class="text-xs font-medium uppercase tracking-wider">Task History</span>
						<span class="text-[10px] text-gray-500 font-mono">{taskList?.total ?? 0} tasks</span>
						<svg
							class="w-3.5 h-3.5 text-gray-400 ml-auto transition-transform {taskHistoryOpen ? '' : 'rotate-180'}"
							viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
						>
							<path d="M18 15l-6-6-6 6" />
						</svg>
					</button>
					{#if taskHistoryOpen}
						<div class="h-[280px] overflow-hidden">
							<div class="px-4 pb-4 h-full flex flex-col">
								{#if runStatus?.running && currentTracking}
									<CurrentTrackingCard tracking={currentTracking} />
								{/if}
								<div class="flex-1 min-h-0">
									{#if !effectivePlanFile}
										<div class="flex items-center justify-center h-full text-sm text-gray-400">
											Plan을 실행하면 관련 작업 이력이 표시됩니다.
										</div>
									{:else if taskList}
										<TaskList
											tasks={taskList.tasks}
											total={taskList.total}
											currentFilter={statusFilter}
											onFilterChange={handleFilterChange}
											onDelete={handleDeleteTask}
											onDeleteCompleted={handleDeleteCompleted}
											onDeleteOld={handleDeleteOld}
										/>
									{/if}
								</div>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
