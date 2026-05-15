<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { RefreshCw, Play, RotateCw } from 'lucide-svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav, { type TabItem } from '$lib/components/layout/TabNav.svelte';
	import {
		PlanRecordsRequestError,
		archiveScheduleApi,
		type ArchiveScheduleDashboardResponse,
		type ArchiveLLMRequestDetail
	} from '$lib/api/plan-records';
	import PlanArchiveSummaryPanel from './PlanArchiveSummaryPanel.svelte';
	import PlanArchiveTargetSelector from './PlanArchiveTargetSelector.svelte';
	import PlanArchiveCandidateTable from './PlanArchiveCandidateTable.svelte';
	import PlanArchiveQueueTable from './PlanArchiveQueueTable.svelte';
	import PlanArchiveHistoryTable from './PlanArchiveHistoryTable.svelte';
	import PlanArchiveRequestDetailModal from './PlanArchiveRequestDetailModal.svelte';
	import type { SelectedTarget } from './planArchiveOperationsState.js';
	import { formatQueueResult, formatRunBacklogResult, formatSyncExecutionsResult } from './planArchiveOperationsState.js';

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
	let runningBacklog = $state(false);
	let syncingExecutions = $state(false);

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

	const SCHEDULE_NOT_FOUND_DETAIL = 'Plan archive schedule not found';

	function describeScheduleMutationError(error: unknown, actionLabel: string) {
		if (error instanceof PlanRecordsRequestError && error.status === 404) {
			if (error.detail === SCHEDULE_NOT_FOUND_DETAIL || error.message === SCHEDULE_NOT_FOUND_DETAIL || dashboard?.schedule === null) {
				return `${actionLabel} 실패: Plan Archive schedule seed 또는 DB 상태를 확인하세요.`;
			}
			return `${actionLabel} 실패: admin API proxy 또는 admin route mismatch 가능성이 있습니다.`;
		}
		return error instanceof Error ? error.message : `${actionLabel} 실패`;
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
			await fetchDashboard();
			showToast(describeScheduleMutationError(e, '정지'), true);
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
			await fetchDashboard();
			showToast(describeScheduleMutationError(e, '재개'), true);
		} finally {
			pausing = false;
		}
	}

	async function handleRunBacklog() {
		if (runningBacklog || selectedTargets.length === 0) return;
		runningBacklog = true;
		try {
			const result = await archiveScheduleApi.runArchiveExecutions({ selected_targets: selectedTargets });
			showToast(formatRunBacklogResult(result));
			await fetchDashboard();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'backlog 실행 실패', true);
		} finally {
			runningBacklog = false;
		}
	}

	async function handleSyncExecutions() {
		if (syncingExecutions) return;
		syncingExecutions = true;
		try {
			const result = await archiveScheduleApi.syncArchiveExecutions();
			showToast(formatSyncExecutionsResult(result));
			await fetchDashboard();
		} catch (e) {
			showToast(e instanceof Error ? e.message : 'sync 실패', true);
		} finally {
			syncingExecutions = false;
		}
	}

	let toastTimer: ReturnType<typeof setTimeout> | null = null;
	function showToast(msg: string, _isError = false) {
		toastMessage = msg;
		if (toastTimer) clearTimeout(toastTimer);
		toastTimer = setTimeout(() => { toastMessage = null; }, 3500);
	}

	const tabs: TabItem[] = [
		{ id: 'candidates', label: '후보 목록' },
		{ id: 'queue', label: 'LLM 요청' },
		{ id: 'history', label: '이력' },
	];
</script>

<svelte:head>
	<title>Plan Archive 운영 | Scheduler</title>
</svelte:head>

<div class="flex h-full flex-col gap-3 overflow-auto p-4 lg:p-6">
	<PageHeader title="Plan Archive 운영">
		<button
			class="inline-flex items-center gap-1 rounded border border-border px-3 py-1 text-xs hover:bg-muted disabled:opacity-50"
			onclick={fetchDashboard}
			disabled={dashboardLoading}
		>
			<RefreshCw class="h-3 w-3 {dashboardLoading ? 'animate-spin' : ''}" />새로고침
		</button>
	</PageHeader>

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

	<!-- Target selector and actions -->
	<div class="flex flex-col gap-2">
		<PlanArchiveTargetSelector bind:selectedTargets />
		<div class="flex flex-wrap items-center gap-2">
			<button
				class="inline-flex items-center gap-1 rounded border border-border px-3 py-1 text-xs hover:bg-muted disabled:opacity-50"
				onclick={handleRunBacklog}
				disabled={runningBacklog || selectedTargets.length === 0}
				title={selectedTargets.length === 0 ? '분석 target을 1개 이상 선택하세요' : 'Backlog 실행'}
			>
				<Play class="h-3 w-3 {runningBacklog ? 'animate-pulse' : ''}" />Backlog 실행
			</button>
			<button
				class="inline-flex items-center gap-1 rounded border border-border px-3 py-1 text-xs hover:bg-muted disabled:opacity-50"
				onclick={handleSyncExecutions}
				disabled={syncingExecutions}
				title="실행 상태 동기화"
			>
				<RotateCw class="h-3 w-3 {syncingExecutions ? 'animate-spin' : ''}" />Sync
			</button>
		</div>
	</div>

	<!-- Tabs -->
	<TabNav tabs={tabs} bind:activeTab variant="secondary" level="secondary" size="compact" />

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
