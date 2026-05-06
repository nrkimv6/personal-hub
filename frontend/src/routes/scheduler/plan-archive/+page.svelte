<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { RefreshCw } from 'lucide-svelte';
	import { archiveScheduleApi, type ArchiveScheduleDashboardResponse, type ArchiveLLMRequestDetail } from '$lib/api/plan-records';
	import PlanArchiveSummaryPanel from './PlanArchiveSummaryPanel.svelte';
	import PlanArchiveTargetSelector from './PlanArchiveTargetSelector.svelte';
	import PlanArchiveCandidateTable from './PlanArchiveCandidateTable.svelte';
	import PlanArchiveQueueTable from './PlanArchiveQueueTable.svelte';
	import PlanArchiveHistoryTable from './PlanArchiveHistoryTable.svelte';
	import PlanArchiveRequestDetailModal from './PlanArchiveRequestDetailModal.svelte';
	import type { SelectedTarget } from './planArchiveOperationsState.js';
	import { formatQueueResult } from './planArchiveOperationsState.js';

	type TabId = 'candidates' | 'queue' | 'history';

	let activeTab = $state<TabId>('candidates');
	let dashboard = $state<ArchiveScheduleDashboardResponse | null>(null);
	let dashboardLoading = $state(false);
	let dashboardError = $state<string | null>(null);
	let dashboardStaleAt = $state<string | null>(null);
	let selectedTargets = $state<SelectedTarget[]>([]);
	let selectedRequest = $state<ArchiveLLMRequestDetail | null>(null);
	let toastMessage = $state<string | null>(null);
	let pausing = $state(false);

	// polling state
	let pollFailCount = $state(0);
	const POLL_NORMAL_MS = 5000;
	const POLL_BACKOFF_MS = 30000;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let pollEnabled = $state(true);

	async function fetchDashboard() {
		if (dashboardLoading) return;
		dashboardLoading = true;
		try {
			dashboard = await archiveScheduleApi.getDashboard();
			dashboardError = null;
			pollFailCount = 0;
			dashboardStaleAt = null;
		} catch (e) {
			pollFailCount += 1;
			if (!dashboardStaleAt) {
				dashboardStaleAt = new Date().toLocaleTimeString();
			}
			dashboardError = e instanceof Error ? e.message : '대시보드 로드 실패';
		} finally {
			dashboardLoading = false;
		}
	}

	function schedulePoll() {
		pollTimer = setTimeout(async () => {
			if (pollEnabled && document.visibilityState !== 'hidden') {
				await fetchDashboard();
			}
			if (pollEnabled) schedulePoll();
		}, pollFailCount >= 3 ? POLL_BACKOFF_MS : POLL_NORMAL_MS);
	}

	function handleVisibilityChange() {
		if (document.visibilityState === 'visible') {
			fetchDashboard();
		}
	}

	onMount(() => {
		fetchDashboard();
		schedulePoll();
		document.addEventListener('visibilitychange', handleVisibilityChange);
	});

	onDestroy(() => {
		pollEnabled = false;
		if (pollTimer) clearTimeout(pollTimer);
		document.removeEventListener('visibilitychange', handleVisibilityChange);
	});

	async function handlePause() {
		pausing = true;
		try {
			await archiveScheduleApi.pause();
			await fetchDashboard();
			showToast('Schedule 정지됨');
		} catch (e) {
			showToast(e instanceof Error ? e.message : '정지 실패', true);
		} finally {
			pausing = false;
		}
	}

	async function handleResume() {
		pausing = true;
		try {
			await archiveScheduleApi.resume();
			await fetchDashboard();
			showToast('Schedule 재개됨');
		} catch (e) {
			showToast(e instanceof Error ? e.message : '재개 실패', true);
		} finally {
			pausing = false;
		}
	}

	let toastTimer: ReturnType<typeof setTimeout> | null = null;
	function showToast(msg: string, _isError = false) {
		toastMessage = msg;
		if (toastTimer) clearTimeout(toastTimer);
		toastTimer = setTimeout(() => { toastMessage = null; }, 3500);
	}

	const tabs: Array<{ id: TabId; label: string }> = [
		{ id: 'candidates', label: '후보 목록' },
		{ id: 'queue', label: 'LLM 요청' },
		{ id: 'history', label: '이력' },
	];
</script>

<svelte:head>
	<title>Plan Archive 운영 | Scheduler</title>
</svelte:head>

<div class="flex h-full flex-col gap-3 overflow-auto p-4 lg:p-6">
	<div class="flex items-center gap-2">
		<h1 class="text-lg font-semibold">Plan Archive 운영</h1>
		<button
			class="ml-auto inline-flex items-center gap-1 rounded border border-border px-3 py-1 text-xs hover:bg-muted"
			onclick={fetchDashboard}
			disabled={dashboardLoading}
		>
			<RefreshCw class="h-3 w-3 {dashboardLoading ? 'animate-spin' : ''}" />새로고침
		</button>
	</div>

	<!-- Summary panel -->
	<PlanArchiveSummaryPanel
		{dashboard}
		loading={dashboardLoading}
		error={dashboardError}
		staleAt={dashboardStaleAt}
		{pausing}
		onPause={handlePause}
		onResume={handleResume}
		onRefresh={fetchDashboard}
	/>

	<!-- Target selector -->
	<PlanArchiveTargetSelector bind:selectedTargets />

	<!-- Tabs -->
	<div class="flex border-b border-border">
		{#each tabs as t}
			<button
				class="px-4 py-2 text-sm {activeTab === t.id ? 'border-b-2 border-primary font-medium' : 'text-muted-foreground hover:text-foreground'}"
				onclick={() => { activeTab = t.id; }}
			>{t.label}</button>
		{/each}
	</div>

	<div class="flex-1 overflow-auto">
		{#if activeTab === 'candidates'}
			<PlanArchiveCandidateTable
				{selectedTargets}
				onQueueSuccess={(r) => {
					showToast(formatQueueResult(r));
					fetchDashboard();
				}}
			/>
		{:else if activeTab === 'queue'}
			<PlanArchiveQueueTable onSelectRequest={(r) => { selectedRequest = r; }} />
		{:else if activeTab === 'history'}
			<PlanArchiveHistoryTable />
		{/if}
	</div>
</div>

<!-- Request detail modal -->
<PlanArchiveRequestDetailModal
	request={selectedRequest}
	onclose={() => { selectedRequest = null; }}
/>

<!-- Toast -->
{#if toastMessage}
	<div class="fixed bottom-4 right-4 z-50 rounded-lg bg-foreground px-4 py-2 text-sm text-background shadow-lg">
		{toastMessage}
	</div>
{/if}
