<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import StatsCard from '$lib/components/auto-next/StatsCard.svelte';
	import TaskList from '$lib/components/auto-next/TaskList.svelte';
	import RunControl from '$lib/components/auto-next/RunControl.svelte';
	import PlanList from '$lib/components/auto-next/PlanList.svelte';
	import LogViewer from '$lib/components/auto-next/LogViewer.svelte';
	import CurrentTaskCard from '$lib/components/auto-next/CurrentTaskCard.svelte';
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
		AutoNextPlanFileResponse
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
	let justCompleted = $state(false);
	let completedTimer: ReturnType<typeof setTimeout> | null = null;
	let lastStartTime = $state<string | null>(null);
	// Phase 1: Collapsible 제어 패널 상태 변수
	let collapsed = $state(false);

	async function loadData() {
		try {
			const results = await Promise.allSettled([
				autoNextStatsApi.stats(),
				autoNextTaskApi.list({
					status: statusFilter,
					limit: 50,
					source_path: runStatus?.plan_file ?? undefined
				}),
				autoNextRunnerApi.status(),
				autoNextPlanApi.list()
			]);

			stats = results[0].status === 'fulfilled' ? results[0].value : null;
			taskList = results[1].status === 'fulfilled' ? results[1].value : null;
			runStatus = results[2].status === 'fulfilled' ? results[2].value : null;
			plans = results[3].status === 'fulfilled' ? results[3].value : null;

			// 실패한 항목 경고 표시
			const failedCount = results.filter(r => r.status === 'rejected').length;
			if (failedCount > 0) {
				console.warn(`[AutoNext] ${failedCount}개 API 호출 실패 - 일부 데이터 없음`);
			}
			error = null;

			// 현재 실행 시작 시간 추적 + 현재 run stats 조회
			if (runStatus?.running && runStatus.start_time) {
				lastStartTime = runStatus.start_time;
				currentRunStats = await autoNextStatsApi.stats(runStatus.start_time);
			} else if (!runStatus?.running) {
				// 실행 중이 아니면 현재 실행 stats 초기화
				currentRunStats = null;
				lastStartTime = null;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleFilterChange(newFilter: string | undefined) {
		statusFilter = newFilter;
		loadData();
	}

	async function handleDeleteTask(id: string) {
		try {
			await autoNextTaskApi.delete(id);
			await loadData();
		} catch (e) {
			error = e instanceof Error ? e.message : '삭제 실패';
		}
	}

	async function handleDeleteCompleted() {
		try {
			await autoNextTaskApi.deleteCompleted(runStatus?.plan_file ?? undefined);
			await loadData();
		} catch (e) {
			error = e instanceof Error ? e.message : '일괄 삭제 실패';
		}
	}

	async function handleDeleteOld(hours: number) {
		try {
			await autoNextTaskApi.deleteOld(hours, runStatus?.plan_file ?? undefined);
			await loadData();
		} catch (e) {
			error = e instanceof Error ? e.message : '이력 정리 실패';
		}
	}

	async function handleRunStatusChange() {
		await loadData();
	}

	onMount(() => {
		loadData();
		pollingController = createSmartPolling(
			loadData,
			() => ({ running: runStatus?.running ?? false })
		);
	});

	onDestroy(() => {
		if (pollingController) {
			pollingController.cleanup();
			pollingController = null;
		}
	});

	// runStatus 변경 시 폴링 간격 재평가 + 완료 감지
	$effect(() => {
		if (runStatus && pollingController) {
			pollingController.refresh();
		}
		// 실행 중 → 중지 전환 감지 → "완료됨" 배지 표시
		if (runStatus && prevRunning && !runStatus.running) {
			justCompleted = true;
			if (completedTimer) clearTimeout(completedTimer);
			completedTimer = setTimeout(() => { justCompleted = false; }, 10000);
		}
		if (runStatus) prevRunning = runStatus.running;
	});
</script>

<!-- Phase 1: flex column 전체 높이 구조 -->
<div class="flex flex-col h-[calc(100vh-4rem)] overflow-hidden">
	<!-- 헤더 -->
	<div class="flex items-center justify-between px-4 py-2 shrink-0">
		<div class="flex items-center gap-3">
			<h1 class="text-2xl font-bold">Auto Next</h1>
			<button
				onclick={loadData}
				disabled={loading}
				class="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
				title="새로고침"
			>
				<svg
					class:animate-spin={loading}
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="M21 2v6h-6" />
					<path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
					<path d="M3 22v-6h6" />
					<path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
				</svg>
			</button>
			<!-- Phase 1: 접기/펼치기 토글 버튼 -->
			<button
				onclick={() => (collapsed = !collapsed)}
				class="p-2 rounded-lg hover:bg-gray-100 transition-colors"
				title={collapsed ? '제어 패널 펼치기' : '제어 패널 접기'}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="transition-transform {collapsed ? 'rotate-180' : ''}"
				>
					<path d="M18 15l-6-6-6 6" />
				</svg>
			</button>
		</div>
		{#if runStatus?.running}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
				<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
				실행 중
			</span>
		{:else if runStatus?.crashed}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-red-100 text-red-800">
				<span class="w-2 h-2 rounded-full bg-red-500"></span>
				비정상 종료 (exit: {runStatus.exit_code})
			</span>
		{:else if justCompleted}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
				<span class="w-2 h-2 rounded-full bg-blue-500"></span>
				완료됨
			</span>
		{:else}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-600">
				<span class="w-2 h-2 rounded-full bg-gray-400"></span>
				대기
			</span>
		{/if}
	</div>

	{#if error}
		<div class="mx-4 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm shrink-0">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex items-center justify-center py-20">
			<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
		</div>
	{:else}
		<!-- Phase 1: 접힌 상태 요약 바 -->
		{#if collapsed}
			<div class="flex items-center gap-3 px-4 py-2 bg-gray-50 border-b shrink-0">
				{#if runStatus?.running}
					<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
						<span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
						실행 중
					</span>
				{:else}
					<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
						<span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>
						대기
					</span>
				{/if}
				{#if taskList?.tasks}
					{@const runningTask = taskList.tasks.find(t => t.status === 'running')}
					{#if runningTask}
						<span class="text-xs text-gray-600 truncate flex-1">{runningTask.text}</span>
					{/if}
				{/if}
				{#if stats}
					<span class="text-xs text-gray-500 shrink-0">{stats.completion_rate.toFixed(1)}%</span>
				{/if}
				{#if runStatus?.current_cycle}
					<span class="text-xs text-gray-500 shrink-0">Cycle {runStatus.current_cycle}</span>
				{/if}
			</div>
		{/if}

		<!-- Phase 1: 제어 패널 (접기/펼치기) -->
		{#if !collapsed}
			<div class="px-4 py-3 shrink-0 space-y-3">
				<!-- Stats -->
				{#if stats}
					<StatsCard {stats} {currentRunStats} isRunning={runStatus?.running ?? false} />
				{/if}

				<!-- RunControl 전체 너비 -->
				<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} />

				<!-- 3-column 그리드: CurrentTaskCard + PlanList -->
				<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
					<!-- Current Task Card -->
					{#if runStatus?.running && taskList?.tasks}
						{@const currentTask = taskList.tasks.find(t => t.status === 'running')}
						{#if currentTask}
							<CurrentTaskCard
								task={currentTask}
								onShowDetail={() => {}}
							/>
						{:else}
							<div></div>
						{/if}
					{:else}
						<div></div>
					{/if}

					<!-- PlanList (2 cols span) -->
					<div class="lg:col-span-2">
						<PlanList {plans} onPlansChange={loadData} />
					</div>
				</div>
			</div>
		{/if}

		<!-- Phase 1: LogViewer flex-1 영역 -->
		<div class="flex-1 min-h-0 px-4 pb-2">
			<LogViewer />
		</div>

		<!-- Phase 1: TaskHistory 하단 고정 패널 (항상 표시) -->
		<div class="h-[280px] shrink-0 overflow-hidden px-4 pb-3">
			{#if !runStatus?.plan_file}
				<div class="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-sm text-gray-500 h-full flex items-center justify-center">
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
	{/if}
</div>
