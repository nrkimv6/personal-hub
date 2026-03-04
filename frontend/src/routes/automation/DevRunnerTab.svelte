<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import TaskList from '$lib/components/dev-runner/TaskList.svelte';
	import RunControl from '$lib/components/dev-runner/RunControl.svelte';
	import PlanList from '$lib/components/dev-runner/PlanList.svelte';
	import RunnerInstanceTab from '$lib/components/dev-runner/RunnerInstanceTab.svelte';
	import CurrentTrackingCard from '$lib/components/dev-runner/CurrentTrackingCard.svelte';
	import MergeQueuePanel from '$lib/components/dev-runner/MergeQueuePanel.svelte';
	import UnifiedLogsView from '$lib/components/dev-runner/UnifiedLogsView.svelte';
	import DevRunnerSettingsPanel from '$lib/components/dev-runner/DevRunnerSettingsPanel.svelte';
	import WorkflowList from '$lib/components/dev-runner/WorkflowList.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import RunStatusBar from '$lib/components/dev-runner/RunStatusBar.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import {
		devRunnerTaskApi,
		devRunnerRunnerApi,
		devRunnerEventApi
	} from '$lib/api';
	import type {
		DevRunnerRunStatusResponse,
		DevRunnerRunnerListItem,
		DevRunnerPlanFileResponse,
		CurrentTrackingResponse
	} from '$lib/api';
	import { fetchPlans as storeFetchPlans, plansStore } from '$lib/stores/devRunnerPlans';

	let { initialPlan = '' }: { initialPlan?: string } = $props();

	let runStatus = $state<DevRunnerRunStatusResponse | null>(null);
	let plans = $derived($plansStore);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let prevRunning = $state(false);
	let prevCycle = $state<number | null>(null);
	let showExecutionModal = $state(false);
	let taskHistoryOpen = $state(false);
	let taskHistoryTab = $state<'tasks' | 'plans' | 'workflows' | 'merge' | 'settings'>('plans');
	let currentTracking = $state<CurrentTrackingResponse | null>(null);
	let selectedPlanPath = $state('');
	let taskListRefreshTick = $state(0);

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
		branch?: string | null;
		orphan?: boolean;
	}

	interface RunnerSource {
		runner_id: string;
		plan_file?: string | null;
		engine?: string | null;
		running?: boolean;
		status?: string;
		start_time?: string | null;
		branch?: string | null;
		orphan?: boolean;
	}

	function createRunnerTab(runner: RunnerSource): RunnerTab {
		return {
			id: runner.runner_id,
			plan_file: runner.plan_file ?? null,
			engine: runner.engine ?? null,
			running: runner.running ?? runner.status === 'running',
			start_time: runner.start_time ? new Date(runner.start_time).toISOString() : null,
			branch: runner.branch ?? null,
			orphan: runner.orphan ?? false,
		};
	}

	function updateRunnerTab(tab: RunnerTab, runner: RunnerSource): RunnerTab {
		return {
			...tab,
			running: runner.running ?? runner.status === 'running',
			plan_file: runner.plan_file ?? tab.plan_file,
			engine: runner.engine ?? tab.engine,
			start_time: runner.start_time ?? tab.start_time,
			orphan: runner.orphan ?? tab.orphan ?? false,
		};
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

			if (status.plan_file) {
				lastPlanFile = status.plan_file;
			}

			// runner 탭 running 상태 동기화 + 신규 runner 추가
			try {
				const runners = await devRunnerRunnerApi.runners();
				const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
				// 기존 탭 상태 갱신
				runnerTabs = runnerTabs.map(tab => {
					const runner = runnerMap.get(tab.id);
					return runner ? updateRunnerTab(tab, runner) : { ...tab, running: false };
				});
				// 신규 runner 탭 추가 (페이지 로드 시 또는 외부에서 시작된 runner)
				for (const runner of runners) {
					if (!runnerTabs.some(t => t.id === runner.runner_id)) {
						runnerTabs = [...runnerTabs, createRunnerTab(runner)];
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
				const data = JSON.parse(e.data) as { runners: { runner_id: string; status: string; pid: string | null; current_cycle: string | null; start_time: string | null; plan_file: string | null; engine: string | null }[] };
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
						return runner ? updateRunnerTab(tab, runner) : { ...tab, running: false };
					});
					// SSE로 발견된 신규 runner 탭 추가
					for (const runner of runners) {
						if (!runnerTabs.some(t => t.id === runner.runner_id)) {
							runnerTabs = [...runnerTabs, createRunnerTab(runner)];
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
			taskListRefreshTick++;
		});
	}

	function handleRunSuccess(response: DevRunnerRunStatusResponse) {
		if (!response.runner_id) return;
		// runStatus 즉시 업데이트 (시작 API 응답에서 확보) — 상단 바 "실행 중" 즉시 표시
		runStatus = response;
		const newTab: RunnerTab = { ...createRunnerTab({ runner_id: response.runner_id, plan_file: response.plan_file, engine: response.engine, start_time: response.start_time }), running: true };
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
			await storeFetchPlans();
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

                // 모바일: 실행 중이면 패널 닫기 (panelOpen 제거됨 - taskHistoryOpen으로 대체)
                if (window.innerWidth < 640) {
                        taskHistoryOpen = !runStatus?.running;
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

		if (elapsedInterval) {
			clearInterval(elapsedInterval);
			elapsedInterval = null;
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
				onSync={fetchPlans}
				onExecute={() => { showExecutionModal = true; }}
				onStopAll={runningCount > 0 ? async () => {
					for (const t of runnerTabs.filter(r => r.running)) {
						await devRunnerRunnerApi.stop(t.id).catch(() => {});
					}
					void pollStatus();
				} : undefined}
			onStopRunner={async (id) => { await devRunnerRunnerApi.stop(id).catch(() => {}); void pollStatus(); }}
			onKillRunner={async (id) => { await devRunnerRunnerApi.kill(id).catch(() => {}); void pollStatus(); }}
			/>

			<!-- 실행 모달 -->
			{#if showExecutionModal}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
					onclick={(e) => { if (e.target === e.currentTarget) showExecutionModal = false; }}
				>
					<div class="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-5">
						<div class="flex items-center justify-between mb-4">
							<h3 class="text-sm font-semibold">실행 설정</h3>
							<button
								onclick={() => { showExecutionModal = false; }}
								class="text-gray-400 hover:text-gray-600 text-lg leading-none"
							>×</button>
						</div>
						<RunControl
							status={runStatus}
							{plans}
							onStatusChange={async () => { showExecutionModal = false; await handleRunStatusChange(); }}
							onStart={(r) => { showExecutionModal = false; handleRunStart(r); }}
							bind:selectedPlan={selectedPlanPath}
							runnerTabs={runnerTabs.map(t => ({ id: t.id, running: t.running }))}
						/>
					</div>
				</div>
			{/if}

			<!-- 모바일: 좌측 패널 오버레이 -->
			{#if taskHistoryOpen}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-40 bg-black/30 sm:hidden"
					onclick={() => { taskHistoryOpen = false; }}
				></div>
			{/if}

			<!-- 2컬럼 레이아웃: 좌측 패널 + 우측 Runner 영역 -->
			<div class="flex-1 min-h-0 flex gap-0 overflow-hidden">

				<!-- 좌측 패널: Plans/Tasks/Merge/설정 (모바일=오버레이, 데스크톱=고정) -->
				<div class="
					{taskHistoryOpen ? 'flex' : 'hidden'} sm:flex
					flex-col border-r overflow-hidden
					w-[300px] sm:w-[340px] shrink-0
					fixed sm:static inset-y-0 left-0 z-50 sm:z-auto
					bg-white
				">
					<!-- 탭 바 -->
					<div class="px-4 pt-2 pb-2 shrink-0 border-b flex items-center gap-2">
						<TabNav
							tabs={[
								{ id: 'plans', label: 'Plans' },
								{ id: 'tasks', label: 'Tasks' },
								{ id: 'workflows', label: '이력' },
								{ id: 'merge', label: 'Merge' },
								{ id: 'settings', label: '설정' },
							]}
							bind:activeTab={taskHistoryTab}
							variant="primary"
							size="compact"
						/>
						<!-- 모바일 닫기 버튼 -->
						<button
							onclick={() => { taskHistoryOpen = false; }}
							class="sm:hidden ml-auto text-gray-400 hover:text-gray-600 text-lg leading-none"
						>×</button>
					</div>
					<!-- 탭 콘텐츠 -->
					<div class="flex-1 min-h-0 overflow-hidden">
						{#if taskHistoryTab === 'tasks'}
							<div class="px-4 pb-4 h-full flex flex-col">
								{#if currentTracking}
									<CurrentTrackingCard tracking={currentTracking} />
								{/if}
								<div class="flex-1 min-h-0 overflow-hidden">
									<TaskList planPath={taskListPlanPath} refreshTick={taskListRefreshTick} />
								</div>
							</div>
						{:else if taskHistoryTab === 'plans'}
							<div class="px-4 pb-4 h-full overflow-hidden flex flex-col">
								<PlanList {plans} onPlansChange={fetchPlans} runningPlanFile={runStatus?.plan_file ?? null} {lastPlanFile} {batchPlans} onPlanSelect={(path) => { selectedPlanPath = path; }} />
							</div>
						{:else if taskHistoryTab === 'workflows'}
							<div class="px-4 pb-4 h-full overflow-auto">
								<WorkflowList />
							</div>
						{:else if taskHistoryTab === 'merge'}
							<div class="h-full overflow-hidden">
								<MergeQueuePanel />
							</div>
						{:else if taskHistoryTab === 'settings'}
							<div class="px-4 pb-4 h-full overflow-auto">
								<DevRunnerSettingsPanel />
							</div>
						{/if}
					</div>
				</div>

				<!-- 우측 영역: Runner 탭 바 + Runner/Logs/Merge 콘텐츠 -->
				<div class="flex-1 min-h-0 flex flex-col overflow-hidden">
					<!-- Runner 탭 바 -->
					<div class="flex items-center gap-1 border-b px-2 py-1 overflow-x-auto shrink-0">
						<!-- 모바일: 좌측 패널 토글 버튼 -->
						<button
							onclick={() => { taskHistoryOpen = !taskHistoryOpen; }}
							class="sm:hidden flex items-center justify-center w-7 h-7 rounded hover:bg-gray-100 text-gray-500 shrink-0 mr-1"
							title="패널 열기"
						>
							<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
						</button>
						{#each runnerTabs as tab (tab.id)}
							<!-- svelte-ignore a11y_interactive_supports_focus -->
							<div
								class="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors cursor-pointer {activeTabId === tab.id ? 'bg-primary/20 text-primary border border-primary/30' : 'text-gray-600 hover:bg-gray-100'}"
								role="tab"
								aria-selected={activeTabId === tab.id}
								onclick={() => { activeTabId = tab.id; }}
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { activeTabId = tab.id; } }}
							>
								{#if tab.running}
								<svg class="w-3 h-3 text-amber-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
							{:else if tab.orphan}
								<span class="w-2 h-2 rounded-full bg-orange-500 shrink-0" title="고아 워크플로우"></span>
							{:else}
								<svg class="w-3 h-3 text-emerald-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
							{/if}
								<span class="max-w-[120px] truncate">{tab.plan_file ? tab.plan_file.split(/[\\/]/).pop()?.replace(/^\d{4}-\d{2}-\d{2}_/, '') : '전체 실행'}</span>
								<button
									class="ml-0.5 w-4 h-4 flex items-center justify-center rounded hover:bg-gray-300 text-gray-400 hover:text-gray-600 text-[10px]"
									onclick={(e) => { e.stopPropagation(); handleCloseTab(tab.id); }}
									title="탭 닫기"
								>×</button>
							</div>
						{/each}
						<!-- 고정 Logs 버튼 -->
						<!-- svelte-ignore a11y_interactive_supports_focus -->
						<div
							class="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors cursor-pointer {activeTabId === '__logs__' ? 'bg-primary/20 text-primary border border-primary/30' : 'text-gray-500 hover:bg-gray-100'}"
							role="tab"
							aria-selected={activeTabId === '__logs__'}
							onclick={() => { activeTabId = '__logs__'; }}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { activeTabId = '__logs__'; } }}
							title="통합 실행 로그"
						>
							<svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
							<span>Logs</span>
						</div>
						<!-- 고정 Merge Queue 버튼 -->
						<!-- svelte-ignore a11y_interactive_supports_focus -->
						<div
							class="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono whitespace-nowrap transition-colors cursor-pointer ml-auto {activeTabId === '__merge__' ? 'bg-primary/20 text-primary border border-primary/30' : 'text-gray-500 hover:bg-gray-100'}"
							role="tab"
							aria-selected={activeTabId === '__merge__'}
							onclick={() => { activeTabId = '__merge__'; }}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { activeTabId = '__merge__'; } }}
							title="Merge Queue"
						>
							<svg class="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
							<span>Merge</span>
						</div>
					</div>

					<!-- Runner 콘텐츠 -->
					<div class="flex-1 min-h-0 overflow-hidden">
						{#if activeTabId === '__logs__'}
							<UnifiedLogsView />
						{:else if activeTabId === '__merge__'}
							<MergeQueuePanel />
						{:else if runnerTabs.length === 0}
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
										orphan={tab.orphan}
										onStop={() => handleTabStop(tab.id)}
										onClose={() => handleCloseTab(tab.id)}
										onBatchPlansChange={(plans) => { batchPlans = plans; }}
									/>
								</div>
							{/each}
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
