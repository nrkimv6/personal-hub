<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import TaskList from '$lib/components/dev-runner/TaskList.svelte';
	import RunControl from '$lib/components/dev-runner/RunControl.svelte';
	import PlanList from '$lib/components/dev-runner/PlanList.svelte';
	import RunnerInstanceTab from '$lib/components/dev-runner/RunnerInstanceTab.svelte';
	import CurrentTrackingCard from '$lib/components/dev-runner/CurrentTrackingCard.svelte';
	import MergeQueuePanel from '$lib/components/dev-runner/MergeQueuePanel.svelte';
	import LogsTab from '$lib/components/dev-runner/LogsTab.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import {
		devRunnerTaskApi,
		devRunnerRunnerApi,
		devRunnerPlanApi,
		devRunnerEventApi
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
	let taskHistoryTab = $state<'tasks' | 'plans' | 'merge' | 'logs'>('plans');
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

	// SSE 연결 상태
	let eventSource: EventSource | null = null;
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

			// runner 탭 running 상태 동기화 + 신규 runner 추가
			try {
				const runners = await devRunnerRunnerApi.runners();
				const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
				// 기존 탭 상태 갱신
				runnerTabs = runnerTabs.map(tab => {
					const runner = runnerMap.get(tab.id);
					return runner ? { ...tab, running: runner.running } : { ...tab, running: false };
				});
				// 신규 runner 탭 추가 (페이지 로드 시 또는 외부에서 시작된 runner)
				for (const runner of runners) {
					if (!runnerTabs.some(t => t.id === runner.runner_id)) {
						runnerTabs = [...runnerTabs, {
							id: runner.runner_id,
							plan_file: runner.plan_file,
							engine: runner.engine,
							running: runner.running,
							start_time: runner.start_time ? new Date(runner.start_time).toISOString() : null,
						}];
					}
				}
				// activeTabId가 없으면 마지막 탭 선택
				if (!activeTabId && runnerTabs.length > 0) {
					activeTabId = runnerTabs[runnerTabs.length - 1].id;
				}
			} catch {
				// runners API 실패 시 무시
			}
		} catch (e) {
			console.warn('[DevRunner] status API 호출 실패', e);
		}
	}

	// ── SSE 연결 ────────────────────────────────────────────────────────────

	function connectSSE() {
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}

		eventSource = devRunnerEventApi.connectEvents();

		eventSource.onopen = () => {
			sseConnected = true;
			sseReconnectDelay = 1000; // 성공 시 delay 리셋
			// fallback 폴링 중단
			if (fallbackTimer) {
				clearInterval(fallbackTimer);
				fallbackTimer = null;
			}
		};

		eventSource.onerror = () => {
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
		};

		// status 이벤트: runner 상태 변경
		eventSource.addEventListener('status', (e: MessageEvent) => {
			try {
				const data = JSON.parse(e.data) as { runners: { runner_id: string; status: string; pid: string | null; current_cycle: string | null; start_time: string | null; plan_file: string | null }[] };
				// runners 배열에서 첫 번째 running runner로 runStatus 갱신
				const runners = data.runners ?? [];
				const runningRunner = runners.find(r => r.status === 'running');
				const anyRunner = runners[0];
				const r = runningRunner ?? anyRunner;
				if (r) {
					runStatus = {
						...(runStatus ?? {} as DevRunnerRunStatusResponse),
						running: r.status === 'running',
						pid: r.pid ? parseInt(r.pid) : null,
						current_cycle: r.current_cycle !== null ? parseInt(r.current_cycle) : null,
						start_time: r.start_time ?? null,
						plan_file: r.plan_file ?? null,
						runner_id: r.runner_id,
					} as DevRunnerRunStatusResponse;
				} else if (runners.length === 0 && runStatus) {
					// 모든 runner 종료
					runStatus = { ...runStatus, running: false };
				}
				// runner 탭 running 상태 동기화 + 신규 runner 탭 추가
				if (runners.length > 0) {
					const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
					runnerTabs = runnerTabs.map(tab => {
						const runner = runnerMap.get(tab.id);
						return runner ? { ...tab, running: runner.status === 'running' } : { ...tab, running: false };
					});
					// SSE로 발견된 신규 runner 탭 추가
					for (const runner of runners) {
						if (!runnerTabs.some(t => t.id === runner.runner_id)) {
							runnerTabs = [...runnerTabs, {
								id: runner.runner_id,
								plan_file: runner.plan_file ?? null,
								engine: null,
								running: runner.status === 'running',
								start_time: runner.start_time ?? null,
							}];
						}
					}
					// activeTabId가 없으면 마지막 탭 선택
					if (!activeTabId && runnerTabs.length > 0) {
						activeTabId = runnerTabs[runnerTabs.length - 1].id;
					}
				}
			} catch {
				// JSON 파싱 오류 무시
			}
		});

		// tracking 이벤트: 현재 추적 태스크 변경
		eventSource.addEventListener('tracking', (e: MessageEvent) => {
			try {
				currentTracking = JSON.parse(e.data) as CurrentTrackingResponse;
			} catch {
				// 무시
			}
		});

		// plan_changed 이벤트: plan_file 변경 → plan 목록 갱신
		eventSource.addEventListener('plan_changed', () => {
			void fetchPlans();
			if (taskListPlanPath) void fetchItems(taskListPlanPath);
		});
	}

	// TaskList용 fetchItems (plan_changed 이벤트에서 호출)
	// DevRunnerTab 자체에서 items를 갖진 않으므로 PlanList 갱신만 처리
	async function fetchItems(_planPath: string) {
		// PlanList는 내부적으로 plans 변경을 감지하므로 fetchPlans()만 호출하면 충분
	}

	function handleRunSuccess(response: DevRunnerRunStatusResponse) {
		if (!response.runner_id) return;
		// runStatus 즉시 업데이트 (시작 API 응답에서 확보) — 상단 바 "실행 중" 즉시 표시
		runStatus = response;
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
		// running이 아닌 탭은 서버에 dismiss 요청하여 다른 기기에서도 사라지게 함
		const tab = runnerTabs.find(t => t.id === runnerId);
		if (tab && !tab.running) {
			devRunnerRunnerApi.dismissTab(runnerId).catch(() => {
				// dismiss 실패해도 로컬 탭은 닫음
			});
		}
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
				const initResponse = await devRunnerRunnerApi.start({ plan_file: decodedPath });
				handleRunStart(initResponse);
				await pollStatus();
				// URL에서 plan param 제거
				const url = new URL(window.location.href);
				url.searchParams.delete('plan');
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

		// 레거시 폴링 정리 (혹시 남아있다면)
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

		// current_cycle 변화 감지 → plans 갱신
		const currentCycle = runStatus?.current_cycle ?? null;
		if (currentCycle !== null && prevCycle !== null && currentCycle !== prevCycle) {
			void fetchPlans();
		}
		prevCycle = currentCycle;

		// 시작 감지 (runningCount 0 → 1+)
		if (!prevRunning && runningCount > 0) {
			lastPlanFile = null;
			if (window.innerWidth < 640) panelOpen = false;
		}

		// 종료 감지 → 모든 runner 종료 시만 plans 갱신
		if (prevRunning && runningCount === 0) {
			justCompleted = true;
			if (completedTimer) clearTimeout(completedTimer);
			completedTimer = setTimeout(() => { justCompleted = false; }, 10000);
			void fetchPlans();
			if (window.innerWidth < 640) panelOpen = true;
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
	let activePlan = $derived(plans?.find(p => p.path === activeTabRunner?.plan_file) ?? null);
	let effectivePlanFile = $derived(activeTabRunner?.plan_file ?? lastPlanFile);
	// TaskList에 표시할 plan path (활성 탭의 plan 또는 사용자가 선택한 plan)
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
							{#if activeTabRunner?.running}
								<div class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
								<span class="text-xs font-medium">실행 중</span>
								{#if runningCount > 1}
									<span class="text-[10px] bg-green-100 text-green-700 px-1 rounded">{runningCount}개</span>
								{/if}
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
							<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} onStart={handleRunStart} bind:selectedPlan={selectedPlanPath} runnerTabs={runnerTabs.map(t => ({ id: t.id, running: t.running }))} />
						</div>

					</div>
				{/if}
			</div>

			<!-- Runner 탭 바 (항상 표시) -->
			{#if runnerTabs.length > 0}
				<div class="flex items-center gap-1 border-b px-2 py-1 overflow-x-auto shrink-0">
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

			<!-- Log Viewer + Runner Panel (2-grid on desktop, stack on mobile) -->
			<div class="flex-1 min-h-0 flex flex-col md:grid md:grid-cols-2 md:gap-0 overflow-hidden">
				<!-- Runner 탭 or 안내 -->
				<div class="flex-1 min-h-0 overflow-hidden">
					{#if runnerTabs.length === 0}
						<div class="flex items-center justify-center h-full text-sm text-gray-400">
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
									onStop={() => handleTabStop(tab.id)}
									onClose={() => handleCloseTab(tab.id)}
									onBatchPlansChange={(plans) => { batchPlans = plans; }}
								/>
							</div>
						{/each}
					{/if}
				</div>

				<!-- Runner Panel: 모바일=하단 고정+접힘/펼침, 데스크톱=우측 패널 -->
				<div class="shrink-0 md:shrink {taskHistoryOpen ? 'max-h-[50dvh]' : ''} md:max-h-none border-t md:border-t-0 md:border-l overflow-hidden flex flex-col">
					<!-- 모바일: 토글 버튼 표시 / 데스크톱: 숨김 (항상 펼침) -->
					<button
						onclick={() => (taskHistoryOpen = !taskHistoryOpen)}
						class="md:hidden flex items-center gap-2 w-full px-4 py-2 hover:bg-gray-50 transition-colors"
					>
						<svg class="w-3.5 h-3.5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
						<span class="text-xs font-medium uppercase tracking-wider">Runner Panel</span>
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
						<span class="text-xs font-medium uppercase tracking-wider">Runner Panel</span>
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
									{ id: 'merge', label: 'Merge Queue' },
									{ id: 'logs', label: '📋 Logs' },
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
									{#if activeTabRunner?.running && currentTracking}
										<CurrentTrackingCard tracking={currentTracking} />
									{/if}
									<div class="flex-1 min-h-0 overflow-hidden">
										<TaskList planPath={taskListPlanPath} />
									</div>
								</div>
							{:else if taskHistoryTab === 'plans'}
								<div class="px-4 pb-4 h-full overflow-hidden flex flex-col">
									<PlanList {plans} onPlansChange={fetchPlans} runningPlanFile={runStatus?.plan_file ?? null} {lastPlanFile} {batchPlans} onPlanSelect={(path) => { selectedPlanPath = path; }} />
								</div>
							{:else if taskHistoryTab === 'merge'}
								<div class="px-4 pb-4 h-full overflow-hidden flex flex-col">
									<MergeQueuePanel />
								</div>
							{:else if taskHistoryTab === 'logs'}
								<div class="h-full overflow-hidden">
									<LogsTab />
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
