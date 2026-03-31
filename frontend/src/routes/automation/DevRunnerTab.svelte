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
	import LogHistoryPanel from '$lib/components/dev-runner/LogHistoryPanel.svelte';
	import DevRunnerSettingsPanel from '$lib/components/dev-runner/DevRunnerSettingsPanel.svelte';
	import WorkflowList from '$lib/components/dev-runner/WorkflowList.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import RunStatusBar from '$lib/components/dev-runner/RunStatusBar.svelte';
	import {
		devRunnerTaskApi,
		devRunnerRunnerApi,
		devRunnerEventApi
	} from '$lib/api';
	import { devRunnerMergeApi, devRunnerPlanApi } from '$lib/api/dev-runner';
	import { encodePathToBase64 } from '$lib/utils/encoding';
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
	let taskHistoryTab = $state<'tasks' | 'plans' | 'merge' | 'logs'>('plans');
	let currentTracking = $state<CurrentTrackingResponse | null>(null);
	let selectedPlanPath = $state('');
	let taskListRefreshTick = $state(0);

	// Phase 2: Plan 상세 모달
	let showPlanModal = $state(false);
	let modalPlan = $state<DevRunnerPlanFileResponse | null>(null);
	let modalSelectedPlan = $state<string>('');
	let modalMode = $state<'single' | 'all'>('single');
	let summaryGenerating = $state(false);
	let summaryGenerated = $state(false);

	async function handleGenerateSummary() {
		if (!modalPlan || summaryGenerating) return;
		summaryGenerating = true;
		summaryGenerated = false;
		try {
			await devRunnerPlanApi.generateSummary(encodePathToBase64(modalPlan.path));
			await fetchPlans();
			// modalPlan summary 갱신
			const updated = $plansStore.find(p => p.path === modalPlan!.path);
			if (updated) modalPlan = updated;
			summaryGenerated = true;
			setTimeout(() => { summaryGenerated = false; }, 2000);
		} catch (e) {
			console.warn('[DevRunner] generateSummary 실패', e);
		} finally {
			summaryGenerating = false;
		}
	}

	// Phase 3: Runner 영역 구조 개편
	let runnerCardCollapsed = $state(false);

	// Phase 4: 종료 시 상태 보존
	let lastPlanFile = $state<string | null>(null);

	// SSE 로그 이벤트 라우팅용 LogViewer ref Map
	interface LogViewerRef {
		injectLine: (text: string) => void;
		injectCompleted: () => void;
		injectMergeCompleted: () => void;
	}
	const logRefs = new Map<string, LogViewerRef>();

	function handlePlanModalOpen(plan: DevRunnerPlanFileResponse) {
		modalPlan = plan;
		modalSelectedPlan = plan.path;
		summaryGenerating = false;
		summaryGenerated = false;
		showPlanModal = true;
		if (window.innerWidth < 640) {
			taskHistoryOpen = false;
		}
	}

	// Merge 탭 대기 건수 뱃지
	let mergeQueuedCount = $state(0);
	let mergeQueuePollInterval: ReturnType<typeof setInterval> | null = null;

	async function pollMergeQueueCount() {
		try {
			const items = await devRunnerMergeApi.queue();
			mergeQueuedCount = items.filter(i => i.status === 'queued').length;
		} catch {
			// 폴링 실패 시 무시
		}
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
		trigger?: string | null;
		orphan?: boolean;
		exit_reason?: string | null;
	}

	interface RunnerSource {
		runner_id: string;
		plan_file?: string | null;
		engine?: string | null;
		running?: boolean;
		status?: string;
		start_time?: string | null;
		branch?: string | null;
		trigger?: string | null;
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
			trigger: runner.trigger ?? null,
			orphan: runner.orphan ?? false,
			exit_reason: (runner as { exit_reason?: string | null }).exit_reason ?? undefined,
		};
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
			orphan: runner.orphan ?? tab.orphan ?? false,
			exit_reason: (runner as { exit_reason?: string | null }).exit_reason ?? tab.exit_reason ?? undefined,
		};
	}

	let runnerTabs = $state<RunnerTab[]>([]);
	let activeTabId = $state<string | null>(null);

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

			// runner 탭 running 상태 동기화 + 신규 runner 추가
			try {
				const allRunners = await devRunnerRunnerApi.runners();
				const runners = allRunners.filter(r => r.visible !== false);
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
				const parsed = JSON.parse(data) as { runners: { runner_id: string; status: string; pid: string | null; current_cycle: string | null; start_time: string | null; plan_file: string | null; engine: string | null; trigger?: string | null }[] };
				const runners = (parsed.runners ?? []).filter(r => r.trigger === 'user' || r.trigger === 'user:all');
				// runner 종료 감지를 위해 업데이트 전 running 상태 캡처
				const prevRunningIds = new Set(runnerTabs.filter(t => t.running).map(t => t.id));
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
					runStatus = { ...runStatus, running: false };
					// runner 목록이 완전히 사라진 경우 (프로세스 종료 + Redis 정리 완료)
					if (prevRunningIds.size > 0) {
						void fetchPlans();
						taskListRefreshTick++;
					}
				}
				if (runners.length > 0) {
					const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
					runnerTabs = runnerTabs.map(tab => {
						const runner = runnerMap.get(tab.id);
						return runner ? updateRunnerTab(tab, runner) : { ...tab, running: false };
					});
					for (const runner of runners) {
						if (!runnerTabs.some(t => t.id === runner.runner_id)) {
							runnerTabs = [...runnerTabs, createRunnerTab(runner)];
						}
					}
					if (!activeTabId && runnerTabs.length > 0) {
						activeTabId = runnerTabs[runnerTabs.length - 1].id;
					}
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
				const { runner_id, line } = JSON.parse(data) as { runner_id: string; line: string };
				// MERGE 로그는 merge_log 이벤트가 동일 라인을 전달하므로 중복 방지를 위해 skip
				if (line.includes('[MERGE]')) return;
				logRefs.get(runner_id)?.injectLine(line);
			} catch { /* 무시 */ }
		} else if (eventName === 'log_completed') {
			try {
				const { runner_id, status } = JSON.parse(data) as { runner_id: string; status?: string };
				const reason = status === 'failed' ? 'error' : 'completed';
				logRefs.get(runner_id)?.injectCompleted(reason);
			} catch { /* 무시 */ }
		} else if (eventName === 'merge_log') {
			try {
				const { runner_id, line } = JSON.parse(data) as { runner_id: string; line: string };
				logRefs.get(runner_id)?.injectLine(line);
			} catch { /* 무시 */ }
		} else if (eventName === 'merge_log_completed') {
			try {
				const { runner_id } = JSON.parse(data) as { runner_id: string };
				logRefs.get(runner_id)?.injectMergeCompleted();
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
			},
			onError: handleSSEError,
			onEvent: handleSSEEvent
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
		logRefs.delete(runnerId);
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

	async function fetchPlans() {
		try {
			await storeFetchPlans();
		} catch (e) {
			console.warn('[DevRunner] plans API 호출 실패', e);
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
			await fetchRunners();
			const msg = `정리 완료: ${result.cleaned}개 항목 제거`;
			console.info('[DevRunner]', msg, result.detail);
		} catch (e) {
			console.warn('[DevRunner] cleanup 실패', e);
		}
	}

	async function fetchRunners() {
		try {
			const allRunners = await devRunnerRunnerApi.runners();
			const runners = allRunners.filter(r => r.visible !== false);
			const runnerMap = new Map(runners.map(r => [r.runner_id, r]));
			runnerTabs = runnerTabs.map(tab => {
				const runner = runnerMap.get(tab.id);
				return runner ? updateRunnerTab(tab, runner) : { ...tab, running: false };
			});
			for (const runner of runners) {
				if (!runnerTabs.some(t => t.id === runner.runner_id)) {
					runnerTabs = [...runnerTabs, createRunnerTab(runner)];
				}
			}
			// dismiss된 탭(서버에서 visible=false) 자동 정리
			runnerTabs = runnerTabs.filter(tab => runnerMap.has(tab.id) || tab.running);
		} catch (e) {
			console.warn('[DevRunner] fetchRunners 실패', e);
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

		// Merge 큐 건수 폴링 시작
		pollMergeQueueCount();
		mergeQueuePollInterval = setInterval(pollMergeQueueCount, 10000);
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
		if (mergeQueuePollInterval) {
			clearInterval(mergeQueuePollInterval);
			mergeQueuePollInterval = null;
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
				onSync={handleSync}
				onCleanup={handleCleanup}
				onExecute={() => { showExecutionModal = true; }}
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

			<!-- 실행 모달 -->
			{#if showExecutionModal}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div
					class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
					onclick={(e) => { if (e.target === e.currentTarget) showExecutionModal = false; }}
				>
					<div class="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-5">
						<div class="flex items-center justify-between mb-4">
							<h3 class="text-sm font-mono font-semibold">실행 설정</h3>
							<button
								onclick={() => { showExecutionModal = false; }}
								class="p-1 rounded-md hover:bg-secondary text-muted-foreground hover:text-foreground"><svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
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

			<!-- 모바일 액션 바 (sm 미만에서만 표시) -->
			<div class="flex items-center gap-1 sm:hidden shrink-0 px-2 pb-1">
				<!-- Plans -->
				<button
					onclick={() => { taskHistoryOpen = true; taskHistoryTab = 'plans'; }}
					class="flex items-center justify-center h-7 w-7 border border-border rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
					title="Plans"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
				</button>
				<!-- Execute -->
				<button
					onclick={() => { showExecutionModal = true; }}
					class="flex items-center justify-center h-7 w-7 border border-border rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
					title="Execute"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
				</button>
				<!-- Tasks -->
				<button
					onclick={() => { taskHistoryOpen = true; taskHistoryTab = 'tasks'; }}
					class="flex items-center justify-center h-7 w-7 border border-border rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
					title="Tasks"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><polyline points="3 6 4 7 6 5"/><polyline points="3 12 4 13 6 11"/><polyline points="3 18 4 19 6 17"/></svg>
				</button>
				<!-- Merge (+ 대기 건수 뱃지) -->
				<button
					onclick={() => { taskHistoryOpen = true; taskHistoryTab = 'merge'; }}
					class="relative flex items-center justify-center h-7 w-7 border border-border rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-foreground"
					title="Merge"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
					{#if mergeQueuedCount > 0}
						<span class="absolute -top-1 -right-1 bg-primary text-primary-foreground text-[8px] font-bold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-0.5">{mergeQueuedCount}</span>
					{/if}
				</button>
				<!-- 종료된 탭 일괄 닫기 -->
				{#if runnerTabs.some(t => !t.running)}
					<button
						onclick={() => { for (const t of runnerTabs.filter(r => !r.running)) { handleCloseTab(t.id); } }}
						class="flex items-center justify-center h-7 w-7 border border-red-200 rounded-md hover:bg-red-100 transition-colors text-red-400 hover:text-red-600"
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
				></div>
			{/if}

			<!-- 2컬럼 레이아웃: 좌측 패널 + 우측 Runner 영역 -->
			<div class="flex-1 min-h-0 flex gap-2 p-2 sm:p-3 overflow-hidden">

				<!-- 좌측 패널: Plans/Tasks/Merge/설정 (모바일=오버레이, 데스크톱=고정) -->
				<div class="
					{taskHistoryOpen ? 'flex' : 'hidden'} sm:flex
					flex-col overflow-hidden
					w-[300px] sm:w-[340px] shrink-0
					fixed sm:static inset-y-0 left-0 z-50 sm:z-auto
					bg-card rounded-md border border-border
				">
					<!-- 탭 바 -->
					<div class="flex items-center border-b border-border shrink-0">
						<button
							onclick={() => { taskHistoryTab = 'plans'; }}
							class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-xs font-mono transition-colors border-b-2 {taskHistoryTab === 'plans' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
							Plans
						</button>
						<button
							onclick={() => { taskHistoryTab = 'tasks'; }}
							class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-xs font-mono transition-colors border-b-2 {taskHistoryTab === 'tasks' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/><polyline points="3 6 4 7 6 5"/><polyline points="3 12 4 13 6 11"/><polyline points="3 18 4 19 6 17"/></svg>
							Tasks
						</button>
												<button
							onclick={() => { taskHistoryTab = 'merge'; }}
							class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-xs font-mono transition-colors border-b-2 {taskHistoryTab === 'merge' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>
							Merge
							{#if mergeQueuedCount > 0}<span class="bg-primary text-primary-foreground text-[8px] font-bold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-0.5">{mergeQueuedCount}</span>{/if}
						</button>
						<button
							onclick={() => { taskHistoryTab = 'logs'; }}
							class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 text-xs font-mono transition-colors border-b-2 {taskHistoryTab === 'logs' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
							Logs
						</button>
												<!-- 모바일 닫기 버튼 -->
						<button
							onclick={() => { taskHistoryOpen = false; }}
							class="sm:hidden ml-auto p-1 rounded-md hover:bg-secondary text-muted-foreground transition-colors shrink-0"
							title="Close"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
						</button>
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
								<PlanList
									{plans}
									onPlansChange={fetchPlans}
									runningPlanFile={runStatus?.plan_file ?? null}
									{lastPlanFile}
									{batchPlans}
									onPlanSelect={(path) => { selectedPlanPath = path; }}
									onExecute={(path) => { selectedPlanPath = path; showExecutionModal = true; }}
									onPlanModalOpen={handlePlanModalOpen}
								/>
							</div>
						{:else if taskHistoryTab === 'merge'}
							<div class="h-full overflow-hidden">
								<MergeQueuePanel />
							<div class="border-t border-gray-200 mt-2"><WorkflowList /></div>
							</div>
						{:else if taskHistoryTab === 'logs'}
							<div class="h-full overflow-hidden">
								<LogHistoryPanel />
							</div>
						{/if}
					</div>
				</div>

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
										trigger={tab.trigger}
										orphan={tab.orphan}
										exitReason={tab.exit_reason}
										onStop={() => handleTabStop(tab.id)}
										onClose={() => handleCloseTab(tab.id)}
										onRestart={() => handleRestart(tab)}
										onBatchPlansChange={(plans) => { batchPlans = plans; }}
										logRef={(ref) => logRefs.set(tab.id, ref)}
									/>
								</div>
							{/each}
						{/if}
					</div>
				</div>
			</div>
		{/if}

		<!-- Plan 상세 모달 (통합: 상세 + RunControl) -->
		{#if showPlanModal && modalPlan}
			<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
			<div
				class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
				onclick={(e) => { if (e.target === e.currentTarget) { showPlanModal = false; modalSelectedPlan = ''; modalMode = 'single'; } }}
			>
				<div class="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden flex flex-col max-h-[90vh]">
					<div class="p-4 border-b border-gray-100 flex items-center justify-between shrink-0">
						<h3 class="text-sm font-semibold truncate flex-1 pr-4">{modalPlan.filename}</h3>
						<button
							onclick={() => { showPlanModal = false; modalSelectedPlan = ''; modalMode = 'single'; }}
							class="text-gray-400 hover:text-gray-600 transition-colors"
						>
							<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
						</button>
					</div>
					<div class="p-5 space-y-4 overflow-y-auto">
						{#if modalMode !== 'all'}
						<div class="bg-blue-50 border border-blue-100 rounded-lg p-3">
							<div class="flex items-center justify-between mb-1">
								<div class="text-[10px] text-blue-400 font-bold uppercase">Summary</div>
								<button
									onclick={handleGenerateSummary}
									disabled={summaryGenerating}
									class="flex items-center gap-1 text-[10px] text-blue-500 hover:text-blue-700 disabled:opacity-50 transition-colors"
									title="요약 생성"
								>
									{#if summaryGenerating}
										<svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
										<span>생성중...</span>
									{:else if summaryGenerated}
										<svg class="w-3 h-3 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
										<span class="text-green-600">완료</span>
									{:else}
										<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
										<span>요약생성</span>
									{/if}
								</button>
							</div>
							<p class="text-xs text-blue-900 leading-relaxed">
								{modalPlan.summary || '요약 정보가 없습니다.'}
							</p>
						</div>
						{/if}

						<div class="grid grid-cols-2 gap-3 text-[11px]">
							<div class="bg-gray-50 rounded p-2">
								<div class="text-gray-400 mb-0.5">Status</div>
								<div class="font-medium">{modalPlan.status}</div>
							</div>
							<div class="bg-gray-50 rounded p-2">
								<div class="text-gray-400 mb-0.5">Progress</div>
								<div class="font-medium">
									{modalPlan.progress ? `${modalPlan.progress.done}/${modalPlan.progress.total}` : '—'}
								</div>
							</div>
						</div>

						<div class="border-t border-gray-100 pt-4">
							<RunControl
								status={runStatus}
								{plans}
								onStatusChange={async () => { showPlanModal = false; modalSelectedPlan = ''; modalMode = 'single'; await handleRunStatusChange(); }}
								onStart={(r) => { showPlanModal = false; modalSelectedPlan = ''; modalMode = 'single'; handleRunStart(r); }}
								bind:selectedPlan={modalSelectedPlan}
								bind:mode={modalMode}
								runnerTabs={runnerTabs.map(t => ({ id: t.id, running: t.running }))}
							/>
						</div>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
