<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import StatsCard from '$lib/components/auto-next/StatsCard.svelte';
	import TaskList from '$lib/components/auto-next/TaskList.svelte';
	import RunControl from '$lib/components/auto-next/RunControl.svelte';
	import PlanList from '$lib/components/auto-next/PlanList.svelte';
	import PlanItems from '$lib/components/auto-next/PlanItems.svelte';
	import LogViewer from '$lib/components/auto-next/LogViewer.svelte';
	import CurrentTaskCard from '$lib/components/auto-next/CurrentTaskCard.svelte';
	import { createSmartPolling } from '$lib/utils/smart-polling';
	import { encodePathToBase64 } from '$lib/utils/encoding';
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
		AutoNextPlanDetailResponse
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
	let selectedPlan = $state<AutoNextPlanFileResponse | null>(null);
	let planDetail = $state<AutoNextPlanDetailResponse | null>(null);
	let planDetailLoading = $state(false);
	let showTaskHistory = $state(
		typeof window !== 'undefined'
			? localStorage.getItem('autoNext_showTaskHistory') === 'true'
			: false
	);

	async function handlePlanSelect(plan: AutoNextPlanFileResponse) {
		if (selectedPlan?.path === plan.path) {
			selectedPlan = null;
			planDetail = null;
			return;
		}
		selectedPlan = plan;
		planDetailLoading = true;
		try {
			const encoded = encodePathToBase64(plan.path);
			planDetail = await autoNextPlanApi.items(encoded);
		} catch {
			planDetail = null;
		} finally {
			planDetailLoading = false;
		}
	}

	function closePlanDetail() {
		selectedPlan = null;
		planDetail = null;
	}

	async function loadData() {
		try {
			const results = await Promise.allSettled([
				autoNextStatsApi.stats(),
				autoNextTaskApi.list({
					status: statusFilter,
					limit: 50,
					source_path: runStatus?.plan_file ?? undefined  // 현재 plan 기준 필터
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

	// localStorage에 showTaskHistory 상태 저장
	$effect(() => {
		if (typeof window !== 'undefined') {
			localStorage.setItem('autoNext_showTaskHistory', String(showTaskHistory));
		}
	});
</script>

<div class="space-y-6">
	<div class="flex items-center justify-between">
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
		<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex items-center justify-center py-20">
			<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
		</div>
	{:else}
		<!-- Stats -->
		{#if stats}
			<StatsCard {stats} {currentRunStats} isRunning={runStatus?.running ?? false} />
		{/if}

		<!-- Current Task Card -->
		{#if runStatus?.running && taskList?.tasks}
			{@const currentTask = taskList.tasks.find(t => t.status === 'running')}
			{#if currentTask}
				<CurrentTaskCard
					task={currentTask}
					onShowDetail={() => { showTaskHistory = true; }}
				/>
			{/if}
		{/if}

		<!-- Run Control + Plans -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} />
			<PlanList {plans} onPlansChange={loadData} onPlanSelect={handlePlanSelect} selectedPath={selectedPlan?.path ?? null} />
		</div>

		<!-- Plan Detail -->
		{#if planDetailLoading}
			<div class="flex items-center justify-center py-8">
				<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
			</div>
		{:else if planDetail}
			<PlanItems detail={planDetail} onClose={closePlanDetail} />
		{/if}

		<!-- Task History Toggle -->
		<div class="flex items-center gap-2">
			<label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer hover:text-gray-800 transition-colors">
				<input
					type="checkbox"
					bind:checked={showTaskHistory}
					class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
				/>
				<span>작업 이력 보기</span>
				<span class="text-xs text-gray-400">(개발자용)</span>
			</label>
		</div>

		<!-- Task List -->
		{#if showTaskHistory && taskList}
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

		<!-- Log Viewer -->
		<LogViewer />
	{/if}
</div>
