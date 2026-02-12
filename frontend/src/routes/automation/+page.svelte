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

<div class="p-6">
	<h1 class="text-2xl font-bold text-foreground mb-4">시스템 자동화</h1>

	<div class="mb-6 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => setMainTab('auto-next')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'auto-next'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				🤖 Auto Next
			</button>
			<button
				onclick={() => setMainTab('sleep-now')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'sleep-now'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				🌙 Sleep Now
			</button>
		</nav>
	</div>

	{#if mainTab === 'auto-next'}
		<AutoNextTab />
	{:else if mainTab === 'sleep-now'}
		<SleepNowTab />
	{/if}
</div>
