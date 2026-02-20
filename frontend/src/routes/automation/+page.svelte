<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import AutoNextTab from './AutoNextTab.svelte';
	import SleepNowTab from './SleepNowTab.svelte';

	type MainTab = 'auto-next' | 'sleep-now';
	let mainTab: MainTab = $state('auto-next');

	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'sleep-now') {
			mainTab = tabParam;
		} else {
			mainTab = 'auto-next';
		}
	});

	function setMainTab(tab: MainTab) {
		const url = new URL($page.url);
		if (tab === 'auto-next') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>시스템 자동화 | Monitor Page</title>
</svelte:head>

<div class="flex flex-col h-screen overflow-hidden">
	<div class="flex items-center gap-4 px-4 lg:px-6 h-12 border-b shrink-0">
		<h1 class="text-sm font-semibold text-foreground">시스템 자동화</h1>
		<nav class="flex gap-1">
			<button
				onclick={() => setMainTab('auto-next')}
				class="px-3 py-1 text-xs font-medium rounded transition-colors {mainTab === 'auto-next'
					? 'bg-blue-50 text-blue-700'
					: 'text-muted-foreground hover:text-foreground hover:bg-gray-50'}"
			>
				🚀 Dev Runner
			</button>
			<button
				onclick={() => setMainTab('sleep-now')}
				class="px-3 py-1 text-xs font-medium rounded transition-colors {mainTab === 'sleep-now'
					? 'bg-blue-50 text-blue-700'
					: 'text-muted-foreground hover:text-foreground hover:bg-gray-50'}"
			>
				Sleep Now
			</button>
		</nav>
	</div>

	<div class="flex-1 overflow-hidden">
		{#if mainTab === 'auto-next'}
			<AutoNextTab />
		{:else if mainTab === 'sleep-now'}
			<div class="p-6 overflow-auto h-full">
				<SleepNowTab />
			</div>
		{/if}
	</div>
</div>
