<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import DevRunnerTab from './DevRunnerTab.svelte';
	import SleepNowTab from './SleepNowTab.svelte';
	import GitReposTab from './GitReposTab.svelte';

	type MainTab = 'dev-runner' | 'sleep-now' | 'git-repos';
	let mainTab: MainTab = $state('dev-runner');

	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'sleep-now') {
			mainTab = tabParam;
		} else if (tabParam === 'git-repos') {
			mainTab = tabParam;
		} else {
			mainTab = 'dev-runner';
		}
	});

	function setMainTab(tab: MainTab) {
		const url = new URL($page.url);
		if (tab === 'dev-runner') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>{mainTab === 'git-repos' ? 'Git 관리' : '시스템 자동화'} | Monitor Page</title>
</svelte:head>

<div class="flex flex-col h-full overflow-hidden">
	<div class="flex items-center gap-4 px-4 lg:px-6 h-12 border-b shrink-0">
		<h1 class="text-base font-bold tracking-tight text-foreground">시스템 자동화</h1>
		<nav class="flex gap-1">
			<button
				onclick={() => setMainTab('dev-runner')}
				class="px-3 py-1 text-xs font-medium rounded transition-colors {mainTab === 'dev-runner'
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
			<button
				onclick={() => setMainTab('git-repos')}
				class="px-3 py-1 text-xs font-medium rounded transition-colors {mainTab === 'git-repos'
					? 'bg-blue-50 text-blue-700'
					: 'text-muted-foreground hover:text-foreground hover:bg-gray-50'}"
			>
				📂 Git 관리
			</button>
		</nav>
	</div>

	<div class="flex-1 overflow-hidden">
		{#if mainTab === 'dev-runner'}
			<DevRunnerTab />
		{:else if mainTab === 'sleep-now'}
			<div class="p-6 overflow-auto h-full">
				<SleepNowTab />
			</div>
		{:else if mainTab === 'git-repos'}
			<div class="overflow-auto h-full">
				<GitReposTab />
			</div>
		{/if}
	</div>
</div>
