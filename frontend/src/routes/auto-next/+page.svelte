<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import StatsCard from '$lib/components/auto-next/StatsCard.svelte';
	import TaskList from '$lib/components/auto-next/TaskList.svelte';
	import RunControl from '$lib/components/auto-next/RunControl.svelte';
	import PlanList from '$lib/components/auto-next/PlanList.svelte';
	import LogViewer from '$lib/components/auto-next/LogViewer.svelte';
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
	let taskList = $state<AutoNextTaskListResponse | null>(null);
	let runStatus = $state<AutoNextRunStatusResponse | null>(null);
	let plans = $state<AutoNextPlanFileResponse[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let statusFilter = $state<string | undefined>(undefined);
	let refreshInterval: ReturnType<typeof setInterval>;

	async function loadData() {
		try {
			const [s, t, r, p] = await Promise.all([
				autoNextStatsApi.stats(),
				autoNextTaskApi.list({ status: statusFilter, limit: 50 }),
				autoNextRunnerApi.status(),
				autoNextPlanApi.list()
			]);
			stats = s;
			taskList = t;
			runStatus = r;
			plans = p;
			error = null;
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

	async function handleRunStatusChange() {
		await loadData();
	}

	onMount(() => {
		loadData();
		refreshInterval = setInterval(loadData, 5000);
	});

	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
	});
</script>

<svelte:head>
	<title>Auto Next - 모니터링</title>
</svelte:head>

<div class="p-4 md:p-6 space-y-6 max-w-7xl mx-auto">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold">Auto Next</h1>
		{#if runStatus?.running}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
				<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
				실행 중
			</span>
		{:else}
			<span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-600">
				<span class="w-2 h-2 rounded-full bg-gray-400"></span>
				중지
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
			<StatsCard {stats} />
		{/if}

		<!-- Run Control + Plans -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<RunControl status={runStatus} {plans} onStatusChange={handleRunStatusChange} />
			<PlanList {plans} />
		</div>

		<!-- Task List -->
		{#if taskList}
			<TaskList
				tasks={taskList.tasks}
				total={taskList.total}
				currentFilter={statusFilter}
				onFilterChange={handleFilterChange}
				onDelete={handleDeleteTask}
			/>
		{/if}

		<!-- Log Viewer -->
		<LogViewer />
	{/if}
</div>
