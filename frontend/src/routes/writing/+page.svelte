<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import WritingTab from './WritingTab.svelte';
	import ReportsTab from './ReportsTab.svelte';

	type MainTab = 'writings' | 'reports';
	let mainTab: MainTab = $state('writings');

	// URL 파라미터에서 탭 읽기 (?tab=llm 은 /llm으로 리다이렉트, 하위호환)
	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'llm') {
			goto('/llm', { replaceState: true });
		} else if (tabParam === 'reports') {
			mainTab = 'reports';
		} else {
			mainTab = 'writings';
		}
	});

	function setMainTab(tab: MainTab) {
		const url = new URL($page.url);
		if (tab === 'writings') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>AI / 글쓰기 | Monitor Page</title>
</svelte:head>

<div class="p-6">
	<h1 class="text-2xl font-bold text-foreground mb-4">AI / 글쓰기</h1>

	<!-- 최상위 탭 -->
	<div class="mb-6 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => setMainTab('writings')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'writings'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				✍️ 글쓰기
			</button>
			<button
				onclick={() => setMainTab('reports')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'reports'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				📋 보고서
			</button>
		</nav>
	</div>

	{#if mainTab === 'writings'}
		<WritingTab />
	{:else if mainTab === 'reports'}
		<ReportsTab />
	{/if}
</div>
