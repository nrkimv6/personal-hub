<script lang="ts">
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import ScheduleListTab from './ScheduleListTab.svelte';
	import RunHistoryTab from './RunHistoryTab.svelte';

	type TabId = 'schedule-list' | 'run-history';
	let activeTab: TabId = $state('schedule-list');

	const tabs = [
		{ id: 'schedule-list', label: '스케줄 목록' },
		{ id: 'run-history', label: '실행 이력' },
	];
</script>

<svelte:head>
	<title>작업 스케줄러 | Monitor Page</title>
</svelte:head>

<TabbedPageLayout
	title="작업 스케줄러"
	subtitle="스케줄 목록과 실행 이력을 같은 상단 계약으로 전환합니다."
	primaryTabs={tabs}
	bind:activePrimaryTab={activeTab}
	primaryQueryParam="tab"
	density="compact"
	containerClass="flex h-full min-h-0 flex-col gap-3 p-4 lg:p-6"
	contentClass="min-h-0 flex-1 overflow-auto"
>
	<div class="flex-1 overflow-auto">
		{#if activeTab === 'schedule-list'}
			<ScheduleListTab />
		{:else if activeTab === 'run-history'}
			<RunHistoryTab />
		{/if}
	</div>
</TabbedPageLayout>
