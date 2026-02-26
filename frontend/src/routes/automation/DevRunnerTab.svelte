<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import TaskList from '$lib/components/dev-runner/TaskList.svelte';
	import RunControl from '$lib/components/dev-runner/RunControl.svelte';
	import PlanList from '$lib/components/dev-runner/PlanList.svelte';
	import RunnerInstanceTab from '$lib/components/dev-runner/RunnerInstanceTab.svelte';
	import CurrentTrackingCard from '$lib/components/dev-runner/CurrentTrackingCard.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import {
		devRunnerTaskApi,
		devRunnerRunnerApi,
		devRunnerPlanApi
	} from '$lib/api';
	import type {
		DevRunnerRunStatusResponse,
		DevRunnerRunnerListItem,
		DevRunnerPlanFileResponse,
		CurrentTrackingResponse
	} from '$lib/api';

	let { initialPlan = '' }: { initialPlan?: string } = $props();

	let runStatus = $state<DevRunnerRunStatusResponse | null>(null);
	let plans = $state<DevRunnerPlanFileResponse[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let pollingController: ReturnType<typeof createSmartPolling> | null = null;
	let prevRunning = $state(false);
	let prevCycle = $state<number | null>(null);
	let justCompleted = $state(false);
	let completedTimer: ReturnType<typeof setTimeout> | null = null;
	let lastStartTime = $state<string | null>(null);
	let panelOpen = $state(true);
	let taskHistoryOpen = $state(false);
	let taskHistoryTab = $state<'tasks' | 'plans'>('plans');
	let currentTracking = $state<CurrentTrackingResponse | null>(null);
	let selectedPlanPath = $state('');
	let trackingInterval: ReturnType<typeof setInterval> | null = null;

	// Phase 4: 종료 시 상태 보존
	let lastPlanFile = $state<string | null>(null);

	// Batch plan 상태 (LogViewer SSE에서 수신)
	let batchPlans = $state<{ name: string; status: 'pending' | 'running' | 'done' }[]>([]);

	// Runner 탭 관리 (멀티 runner 지원)
	interface RunnerTab {
		id: string;
		plan_file: string | null;
		engine: string | null;
		running: boolean;
		start_time: string | null;
	}
	let runnerTabs = $state<RunnerTab[]>([]);
	let activeTabId = $state<string | null>(null);

	// Phase 1: elapsed 타이머
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
			const status = await devRunnerRunnerApi.status();
			runStatus = status;

			if (status.running && status.start_time) {
				lastStartTime = status.start_time;
				if (status.plan_file) {
					lastPlanFile = status.plan_file;
				}
			} else if (!status.running) {
				if (status.plan_file) {
					lastPlanFile = status.plan_file;
				}
				lastStartTime = null;
			}

			// runner 탭 running 상태 동기화
			try {
				const runners = await devRunnerRunnerApi.runners();
				const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
				runnerTabs = runnerTabs.map(tab => {
					const runner = runnerMap.get(tab.id);
					return runner ? { ...tab, running: runner.running } : { ...tab, running: false };
				});
			} catch {
				// runners API 실패 시 무시
			}
		} catch (e) {
			console.warn('[DevRunner] status API 호출 실패', e);
		}
	}

	function handleRunSuccess(response: DevRunnerRunStatusResponse) {
		if (!response.runner_id) return;
		const newTab: RunnerTab = {
			id: response.runner_id,
			plan_file: response.plan_file,
			engine: response.engine ?? null,
			running: true,
			start_time: response.start_time,
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
		runnerTabs = runnerTabs.filter(t => t.id !== runnerId);
		if (activeTabId === runnerId) {
			activeTabId = runnerTabs.length > 0 ? runnerTabs[runnerTabs.length - 1].id : null;
		}
	}

	function handleTabStop(runnerId: string) {
		runnerTabs = runnerTabs.map(t => t.id === runnerId ? { ...t, running: false } : t);
		void pollStatus();
	}

	async function fetchPlans() {
		try {
			plans = await devRunnerPlanApi.list();
		} catch (e) {
			console.warn('[DevRunner] plans API 호출 실패', e);
		}
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
                }

                // 초기 로드
                await Promise.all([pollStatus(), fetchPlans()]);

                if (window.innerWidth < 640) {
                        panelOpen = !runStatus?.running;
                }
                loading = false;
                error = null;

		// Phase 4: initialPlan이 있으면 자동 실행
		if (initialPlan) {
			try {
				const decodedPath = atob(initialPlan);
				await devRunnerRunnerApi.start({ plan_file: decodedPath });
				await pollStatus();
				// URL에서 plan param 제거
				const url = new URL(window.location.href);
				url.searchParams.delete('plan');
				goto(url.toString(), { replaceState: true, keepFocus: true });
			} catch (e) {
				console.warn('[DevRunner] initialPlan 자동 실행 실패', e);
			}
		}

		// 폴링은 status만 (3초/15초 간격)
		pollingController = createSmartPolling(
			pollStatus,
			() => ({ running: runStatus?.running ?? false })
		);

		// TaskTracker tracking 정보 폴링 (5초 간격)
		trackingInterval = setInterval(async () => {
			try {
				currentTracking = await devRunnerTaskApi.currentTracking();
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

		// current_cycle 변화 감지 → plans 갱신
		const currentCycle = runStatus?.current_cycle ?? null;
		if (currentCycle !== null && prevCycle !== null && currentCycle !== prevCycle) {
			void fetchPlans();
		}
		prevCycle = currentCycle;

		// 시작 감지
		if (runStatus && !prevRunning && runStatus.running) {
                        lastPlanFile = null;
                        if (window.innerWidth < 640) panelOpen = false;
		}

		// 종료 감지 → plans 갱신
		if (runStatus && prevRunning && !runStatus.running) {
			justCompleted = true;
			if (completedTimer) clearTimeout(completedTimer);
			completedTimer = setTimeout(() => { justCompleted = false; }, 10000);
                        void fetchPlans();
                        if (window.innerWidth < 640) panelOpen = true;
                }

		// elapsed 타이머 관리
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
	let activePlan = $derived(plans?.find(p => p.path === runStatus?.plan_file) ?? null);
	let effectivePlanFile = $derived(runStatus?.plan_file ?? lastPlanFile);
	// TaskList에 표시할 plan path (실행 중인 plan 또는 사용자가 선택한 plan)
	let taskListPlanPath = $derived(effectivePlanFile ?? selectedPlanPath ?? null);
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
			<!-- Collapsible Control Panel -->
			<div class="border-b">
				<!-- Collapsible trigger bar (always visible) -->
				<button
					onclick={() => (panelOpen = !panelOpen)}
					class="flex items-center justify-between w-full px-4 py-2.5 hover:bg-gray-50 transition-colors"
				>
					<div class="flex items-center gap-4 min-w-0">
						<!-- Status indicator -->
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
								{:else if effectivePlanFile}
									<div class="flex items-center gap-1.5 shrink-0">
										<svg class="w-3 h-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
										<span class="text-xs text-gray-500 font-mono truncate max-w-[200px]">
											{effectivePlanFile.split(/[\\/]/).pop()}
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
					<div class="px-4 pb-4 flex flex-col gap-4 bg-gray-50">
						<!-- RunControl - full width card -->
						<div class="bg-white border rounded-lg p-4">
							<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} onStart={handleRunStart} bind:selectedPlan={selectedPlanPath} />
						</div>

						<!-- Runner 서브탭 바 -->
						{#if runnerTabs.length > 0}
							<div class="flex items-center gap-1 bg-white border rounded-lg px-2 py-1 overflow-x-auto">
								{#each runnerTabs as tab (tab.id)}
									<!-- svelte-ignore a11y_interactive_supports_focus -->
									<div
										class="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors cursor-pointer {activeTabId === tab.id ? 'bg-blue-50 text-blue-700 border border-blue-200' : 'text-gray-600 hover:bg-gray-100'}"
										role="tab"
										aria-selected={activeTabId === tab.id}
										onclick={() => { activeTabId = tab.id; }}
										onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { activeTabId = tab.id; } }}
									>
										<span>{tab.running ? '⏳' : '✅'}</span>
										<span class="max-w-[120px] truncate">{tab.plan_file ? tab.plan_file.split(/[\\/]/).pop() : '전체 실행'}</span>
										<button
											class="ml-0.5 w-4 h-4 flex items-center justify-center rounded hover:bg-gray-300 text-gray-400 hover:text-gray-600 text-[10px]"
											onclick={(e) => { e.stopPropagation(); handleCloseTab(tab.id); }}
											title="탭 닫기"
										>×</button>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Log Viewer + Plans & Tasks (2-grid on desktop, stack on mobile) -->
			<div class="flex-1 min-h-0 flex flex-col md:grid md:grid-cols-2 md:gap-0 overflow-hidden">
				<!-- Runner 탭 or 안내 -->
				<div class="flex-1 min-h-0 overflow-hidden">
					{#if activeTabId}
						{@const activeTab = runnerTabs.find(t => t.id === activeTabId)}
						{#if activeTab}
							<RunnerInstanceTab
								runnerId={activeTab.id}
								planFile={activeTab.plan_file}
								running={activeTab.running}
								engine={activeTab.engine}
								startTime={activeTab.start_time}
								onStop={() => handleTabStop(activeTab.id)}
								onClose={() => handleCloseTab(activeTab.id)}
							/>
						{/if}
					{:else}
						<div class="flex items-center justify-center h-full text-sm text-gray-400">
							실행 버튼을 눌러 plan-runner를 시작하세요
						</div>
					{/if}
				</div>

				<!-- Plans & Tasks: 모바일=하단 고정+접힘/펼침, 데스크톱=우측 패널 -->
				<div class="shrink-0 md:shrink {taskHistoryOpen ? 'max-h-[50dvh]' : ''} md:max-h-none border-t md:border-t-0 md:border-l overflow-hidden flex flex-col">
					<!-- 모바일: 토글 버튼 표시 / 데스크톱: 숨김 (항상 펼침) -->
					<button
						onclick={() => (taskHistoryOpen = !taskHistoryOpen)}
						class="md:hidden flex items-center gap-2 w-full px-4 py-2 hover:bg-gray-50 transition-colors"
					>
						<svg class="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
						<span class="text-xs font-medium uppercase tracking-wider">Plans & Tasks</span>
						{#if taskHistoryTab === 'tasks'}
							{#if taskListPlanPath}
								<span class="text-[10px] text-gray-400 font-mono truncate max-w-[160px]">{taskListPlanPath.split(/[\\/]/).pop()}</span>
							{/if}
						{:else}
							<div class="h-3 w-px bg-gray-200 shrink-0"></div>
							<span class="text-[10px] text-gray-500 font-mono shrink-0">{plans.length} plans</span>
						{/if}
						<svg
							class="w-3.5 h-3.5 text-gray-400 ml-auto shrink-0 transition-transform {taskHistoryOpen ? '' : 'rotate-180'}"
							viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
						>
							<path d="M18 15l-6-6-6 6" />
						</svg>
					</button>
					<!-- 데스크톱 헤더 (항상 표시) -->
					<div class="hidden md:flex items-center gap-2 px-4 py-2 border-b">
						<svg class="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
						<span class="text-xs font-medium uppercase tracking-wider">Plans & Tasks</span>
						{#if taskHistoryTab === 'tasks'}
							{#if taskListPlanPath}
								<span class="text-[10px] text-gray-400 font-mono truncate max-w-[160px]">{taskListPlanPath.split(/[\\/]/).pop()}</span>
							{/if}
						{:else}
							<div class="h-3 w-px bg-gray-200 shrink-0"></div>
							<span class="text-[10px] text-gray-500 font-mono shrink-0">{plans.length} plans</span>
						{/if}
					</div>
					<!-- 콘텐츠: 데스크톱은 항상 표시, 모바일은 토글 -->
					<div class="{taskHistoryOpen ? 'flex' : 'hidden'} md:flex flex-col flex-1 min-h-0 md:h-auto">
						<!-- 탭 버튼 -->
						<div class="px-4 pt-2 shrink-0">
							<TabNav
								tabs={[
									{ id: 'tasks', label: 'Tasks' },
									{ id: 'plans', label: 'Plans' },
								]}
								bind:activeTab={taskHistoryTab}
								variant="primary"
								size="compact"
							/>
						</div>
						<!-- 탭 콘텐츠 -->
						<div class="flex-1 min-h-0 overflow-hidden">
							{#if taskHistoryTab === 'tasks'}
								<div class="px-4 pb-4 h-full flex flex-col">
									{#if runStatus?.running && currentTracking}
										<CurrentTrackingCard tracking={currentTracking} />
									{/if}
									<div class="flex-1 min-h-0 overflow-hidden">
										<TaskList planPath={taskListPlanPath} />
									</div>
								</div>
							{:else}
								<div class="px-4 pb-4 h-full overflow-hidden flex flex-col">
									<PlanList {plans} onPlansChange={fetchPlans} runningPlanFile={runStatus?.plan_file ?? null} {lastPlanFile} {batchPlans} onPlanSelect={(path) => { selectedPlanPath = path; }} />
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
