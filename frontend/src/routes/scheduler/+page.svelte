<script lang="ts">
	import TabNav from '$lib/components/layout/TabNav.svelte';
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

<div class="flex flex-col h-full overflow-hidden">
	<div class="flex items-center gap-4 px-4 lg:px-6 h-12 border-b shrink-0">
		<h1 class="text-base font-bold tracking-tight text-foreground">작업 스케줄러</h1>
		<TabNav {tabs} bind:activeTab variant="primary" size="compact" queryParam="tab" />
	</div>

	<div class="flex-1 overflow-auto">
		{#if activeTab === 'schedule-list'}
			<ScheduleListTab />
		{:else if activeTab === 'run-history'}
			<RunHistoryTab />
		{/if}
	</div>
</div>
